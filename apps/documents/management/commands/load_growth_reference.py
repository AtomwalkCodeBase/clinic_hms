"""
Convert a WHO / IAP LMS table into config/growth_reference/{indicator}_{sex}_{source}.csv

  python manage.py load_growth_reference wfa-boys-zscore-expanded-tables.xlsx \
      --indicator wfa --sex male --source who
  python manage.py load_growth_reference iap_height_girls_lms.csv \
      --indicator lhfa --sex female --source iap --age-unit years

Accepts .csv or .xlsx. Age column is auto-detected (Day / Month / Age / Years);
override the unit with --age-unit days|months|years.
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.documents.services.config import GROWTH_REFERENCE_DIR

DAYS_PER_MONTH = 30.4375


def _rows(path: Path):
    if path.suffix.lower() in (".xlsx", ".xls"):
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        header = [str(h or "").strip() for h in next(it)]
        for row in it:
            yield dict(zip(header, row))
    else:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            yield from csv.DictReader(fh)


class Command(BaseCommand):
    help = "Load a WHO/IAP LMS growth reference table"

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--indicator", required=True, choices=["wfa", "lhfa", "hcfa", "bfa"])
        parser.add_argument("--sex", required=True, choices=["male", "female"])
        parser.add_argument("--source", required=True, choices=["who", "iap"])
        parser.add_argument("--age-unit", choices=["days", "months", "years"])

    def handle(self, *args, **o):
        src = Path(o["file"])
        if not src.exists():
            raise CommandError(f"{src} not found")
        out_rows = []
        for row in _rows(src):
            keys = {k.lower().strip(): k for k in row if k}
            age_key = next((keys[k] for k in ("day", "days", "month", "months", "age", "years", "year")
                            if k in keys), None)
            if not age_key or row.get(age_key) in (None, ""):
                continue
            unit = o["age_unit"] or {"day": "days", "days": "days", "month": "months",
                                     "months": "months", "years": "years", "year": "years"}.get(
                age_key.lower().strip(), "months")
            age = float(row[age_key])
            age_m = age / DAYS_PER_MONTH if unit == "days" else age * 12 if unit == "years" else age
            try:
                L, M, S = (float(row[keys[k]]) for k in ("l", "m", "s"))
            except (KeyError, TypeError, ValueError):
                raise CommandError("Table needs L, M and S columns")
            out_rows.append((round(age_m, 4), L, M, S))

        if not out_rows:
            raise CommandError("No rows read")
        GROWTH_REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        dest = GROWTH_REFERENCE_DIR / f"{o['indicator']}_{o['sex']}_{o['source']}.csv"
        with open(dest, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["age_months", "L", "M", "S"])
            w.writerows(sorted(out_rows))
        self.stdout.write(self.style.SUCCESS(
            f"Wrote {len(out_rows)} rows ({out_rows[0][0]}-{out_rows[-1][0]} months) to {dest}"))
