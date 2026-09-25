#!/usr/bin/env bash
# deploy/install.sh — set up Redis + Celery worker + Beat + Flower as systemd
# services on an Ubuntu EC2 server. Idempotent: safe to re-run after changes.
#
#   sudo deploy/install.sh                       # app in /opt/hms, runs as ubuntu
#   sudo deploy/install.sh --app-dir /srv/hms --user hms
#   sudo deploy/install.sh --with-web            # also gunicorn (hms-web.service)
#   sudo deploy/install.sh --no-redis            # broker is ElastiCache / elsewhere
#
# Prerequisites: the repo checked out at --app-dir, a venv at <app-dir>/venv
# with `pip install -r requirements.txt` done, the app's .env filled in, and
# `python manage.py migrate` run. See deploy/README.md.
set -euo pipefail

APP_DIR=/opt/hms
APP_USER=ubuntu
WITH_WEB=0
WITH_REDIS=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir) APP_DIR="$2"; shift 2 ;;
    --user) APP_USER="$2"; shift 2 ;;
    --with-web) WITH_WEB=1; shift ;;
    --no-redis) WITH_REDIS=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
[[ -x "$APP_DIR/venv/bin/celery" ]] || { echo "no $APP_DIR/venv/bin/celery — create the venv and pip install first" >&2; exit 1; }
[[ -f "$APP_DIR/.env" ]] || echo "WARNING: $APP_DIR/.env not found — the services will start with defaults" >&2

render() {  # render <template> <dest>
  sed -e "s#@APP_DIR@#${APP_DIR}#g" -e "s#@APP_USER@#${APP_USER}#g" "$1" > "$2"
}

echo "== Redis"
if [[ $WITH_REDIS -eq 1 ]]; then
  command -v redis-server >/dev/null || { apt-get update -qq && apt-get install -y -qq redis-server; }
  install -m 0644 "$HERE/redis/hms.conf" /etc/redis/hms.conf
  grep -q '^include /etc/redis/hms.conf' /etc/redis/redis.conf || echo 'include /etc/redis/hms.conf' >> /etc/redis/redis.conf
  systemctl enable --now redis-server
  systemctl restart redis-server
  redis-cli ping
else
  echo "skipped (--no-redis): make sure CELERY_BROKER_URL in .env points at your broker"
fi

echo "== Directories and tunables"
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/logs"
install -d -m 0755 /etc/hms
[[ -f /etc/hms/celery.env ]] || install -m 0640 -o root -g "$APP_USER" "$HERE/celery.env.example" /etc/hms/celery.env

echo "== systemd units"
UNITS=(hms-celery-worker hms-celery-llm hms-celery-beat hms-flower)
[[ $WITH_WEB -eq 1 ]] && UNITS+=(hms-web)
for u in "${UNITS[@]}"; do
  render "$HERE/systemd/$u.service" "/etc/systemd/system/$u.service"
  if [[ $WITH_REDIS -eq 0 ]]; then   # no local Redis to wait for
    sed -i -e 's/ redis-server.service//g' "/etc/systemd/system/$u.service"
  fi
done
systemctl daemon-reload
for u in "${UNITS[@]}"; do systemctl enable "$u"; systemctl restart "$u"; done

echo "== logrotate"
render "$HERE/logrotate/hms-celery" /etc/logrotate.d/hms-celery

echo "== .env checks"
check() { grep -q "^$1=" "$APP_DIR/.env" 2>/dev/null || echo "  add to .env: $1=$2"; }
check CELERY_BROKER_URL "redis://127.0.0.1:6379/0"
check CELERY_UI_PROCESS_CONTROL "False"
grep -q '^CELERY_UI_PROCESS_CONTROL=False' "$APP_DIR/.env" 2>/dev/null \
  || echo "  CELERY_UI_PROCESS_CONTROL must be False here (systemd owns the processes)"

sleep 3
echo "== status"
systemctl --no-pager --lines=0 status "${UNITS[@]}" || true
echo
echo "Done. Logs: $APP_DIR/logs/celery-*.log   |   journalctl -u hms-celery-worker -f"
echo "Flower: ssh -L 5555:127.0.0.1:5555 $APP_USER@<server>  then open http://localhost:5555"
