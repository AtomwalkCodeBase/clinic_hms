#!/bin/bash
# Atomwalk Healthcare Platform — Quick Start
# Run this from D:\hospital_management_system

echo "=== Atomwalk Healthcare Platform Setup ==="

# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy .env
cp .env.example .env
echo "  → Edit .env with your PostgreSQL credentials before proceeding"

# 4. Create Registry DB (run once)
# psql -U postgres -c "CREATE DATABASE atomwalk_registry;"

# 5. Run Registry migrations
python manage.py migrate --database=default

# 6. Create Django superuser (for /django-admin/)
python manage.py createsuperuser

# 7. Provision your first tenant
python manage.py provision_tenant \
  --name "Demo Hospital" \
  --subdomain demo-hospital \
  --city Mumbai \
  --state Maharashtra \
  --admin-mobile 9999999999 \
  --admin-email admin@demohospital.in \
  --tier growth

echo ""
echo "=== Setup Complete ==="
echo "  Run: python manage.py runserver"
echo "  API Docs: http://localhost:8000/api/docs/"
echo "  Staff login: POST http://localhost:8000/api/v1/auth/login/staff/"
echo ""
