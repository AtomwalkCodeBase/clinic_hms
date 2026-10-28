"""python manage.py export_seed [--dir seed_data]

Writes everything in the databases to JSON files, one for the shared database (default.json) and one for each hospital's own database, so the same
data can be loaded on another server with `load_seed`. The files hold patient data and password hashes: keep them out of git. Files kept in the
bucket (reports, photos) are not copied; the server has to use the same bucket and folder."""
import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.hospital_master.models import Hospital
from apps.hospital_master.services import ensure_hospital_db

SHARED_MODELS = ["auth.User", "patients", "documents", "hospital_master"]
HOSPITAL_APPS = ["hospital_setup", "hospital_patients", "opd", "billing"]


class Command(BaseCommand):
    help = "Export the shared database and every hospital database to JSON files."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default="seed_data", help="Folder to write into (default: seed_data).")

    @staticmethod
    def _dump(path, labels, database):
        with open(path, "w", encoding="utf-8") as file:           # utf-8 on every platform (names such as "Hepatitis B - 2" and units carry symbols)
            call_command("dumpdata", *labels, database=database, indent=1, stdout=file)

    def handle(self, *args, **options):
        out = Path(options["dir"])
        out.mkdir(parents=True, exist_ok=True)

        self._dump(out / "default.json", SHARED_MODELS, "default")
        hospitals = list(Hospital.objects.using("default").order_by("pk").values("pk", "name", "db_name"))
        for hospital in hospitals:
            ensure_hospital_db(hospital["db_name"])
            self._dump(out / f"{hospital['db_name']}.json", HOSPITAL_APPS, hospital["db_name"])
        (out / "manifest.json").write_text(json.dumps({"hospitals": hospitals}, indent=1), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Exported the shared database and {len(hospitals)} hospital database(s) to {out}/"))
