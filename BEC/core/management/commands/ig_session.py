"""
ig_session
==========
Manage the burner-account Instagram session cookies.

    python manage.py ig_session import /path/to/cookie-export.json
    python manage.py ig_session test
"""

from django.core.management.base import BaseCommand, CommandError

from scraper import session_store


class Command(BaseCommand):
    help = "Import or test the Instagram session cookies."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["import", "test"])
        parser.add_argument("path", nargs="?", help="Cookie export JSON (for import).")

    def handle(self, *args, **opts):
        action = opts["action"]
        if action == "import":
            if not opts["path"]:
                raise CommandError("import requires a path to a cookie export JSON")
            cookies = session_store.import_cookies(opts["path"])
            self.stdout.write(self.style.SUCCESS(
                f"Imported {len(cookies)} cookies. Run `ig_session test` to verify."
            ))
        elif action == "test":
            ok, detail = session_store.test_session()
            if ok:
                self.stdout.write(self.style.SUCCESS(f"Session OK: {detail}"))
            else:
                self.stdout.write(self.style.ERROR(f"Session INVALID: {detail}"))
                raise SystemExit(1)
