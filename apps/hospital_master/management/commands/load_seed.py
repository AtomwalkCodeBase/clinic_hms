"""python manage.py load_seed [--dir seed_data] [--replace]

Loads the files written by `export_seed` into freshly migrated databases: the shared one first, then a database for each hospital (created and
migrated here if it does not exist). A database that already holds data is left alone unless --replace is given, which drops and recreates the
hospital databases."""
import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.utils import OperationalError

from apps.hospital_master.models import Hospital, Schedule, ScheduleRule
from apps.hospital_master.services import create_hospital_database, ensure_hospital_db, run_hospital_migrations
from apps.hospital_setup.models import OptionList, StaffUser


class Command(BaseCommand):
    help = "Load the JSON files of export_seed into the shared database and the hospital databases."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default="seed_data", help="Folder with the exported files (default: seed_data).")
        parser.add_argument("--replace", action="store_true", help="Drop and recreate hospital databases that already exist.")

    @staticmethod
    def _database_exists(alias):
        try:
            connections[alias].ensure_connection()
            return True
        except OperationalError:
            return False

    def handle(self, *args, **options):
        folder = Path(options["dir"])
        manifest = folder / "manifest.json"
        if not manifest.exists():
            raise CommandError(f"{manifest} not found: run export_seed first, and give --dir.")
        hospitals = json.loads(manifest.read_text(encoding="utf-8"))["hospitals"]

        if Hospital.objects.using("default").exists() and not options["replace"]:
            raise CommandError("The shared database already has hospitals. Load into an empty, migrated database, or pass --replace.")

        # The migrations seeded a default vaccination schedule: the file has its own copy, with the same ids
        ScheduleRule.objects.using("default").all().delete()
        Schedule.objects.using("default").all().delete()
        call_command("loaddata", str(folder / "default.json"), database="default", verbosity=0)
        self.stdout.write("Loaded the shared database.")

        for hospital in hospitals:
            alias = hospital["db_name"]
            ensure_hospital_db(alias)
            if self._database_exists(alias):
                if options["replace"]:
                    create_hospital_database(alias)          # drops the stale copy and creates it again
                elif StaffUser.objects.using(alias).exists():
                    raise CommandError(f"{alias} already has data. Pass --replace to drop and recreate it.")
            else:
                create_hospital_database(alias)
            run_hospital_migrations(alias)
            OptionList.objects.using(alias).all().delete()       # the migration's dropdown lists: the file has the hospital's own
            call_command("loaddata", str(folder / f"{alias}.json"), database=alias, verbosity=0)
            self.stdout.write(f"Loaded {hospital['name']} ({alias}).")
        self.stdout.write(self.style.SUCCESS("Done."))
