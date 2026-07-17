"""
seed_client_user
================
Create the single shared client user + DRF token, and seed the default
scraper_config rows (doc_ids, delays, provider order). Idempotent.

    python manage.py seed_client_user --username cliente --password 'secret'
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from core.models import ScraperConfig

DEFAULT_CONFIG = {
    # GraphQL doc_id for the reels-tab clips connection. Rotates every 2-4
    # weeks — refresh via DevTools (see README) and edit here in admin.
    "doc_id_reels_tab": {"value": "8526372674115715"},
    "page_size": {"value": 12},
    "max_pages_per_account": {"value": 3},
    "min_delay_s": {"value": 25},
    "global_request_budget": {"value": 40},
    "provider_order": {"value": ["graphql", "instaloader"]},
    "impersonate": {"value": "chrome124"},
}


class Command(BaseCommand):
    help = "Create the client user + token and seed scraper_config defaults."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="cliente")
        parser.add_argument("--password", required=True)

    def handle(self, *args, **opts):
        username = opts["username"]
        user, created = User.objects.get_or_create(username=username)
        user.set_password(opts["password"])
        user.is_staff = True  # so they (or you) can reach /admin if needed
        user.is_superuser = True
        user.save()
        token, _ = Token.objects.get_or_create(user=user)
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} user '{username}'. Token: {token.key}"
            )
        )

        for key, val in DEFAULT_CONFIG.items():
            obj, made = ScraperConfig.objects.get_or_create(key=key, defaults={"value": val})
            if made:
                self.stdout.write(f"  seeded scraper_config['{key}'] = {val}")
        self.stdout.write(self.style.SUCCESS("scraper_config defaults ensured."))
