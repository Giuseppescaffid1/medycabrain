"""
Verify the Instagram Graph API setup, end to end, before trusting it.

    python manage.py graph_check

Answers, in order:
  1. is the token valid, and who is it?
  2. which Instagram Business account calls business_discovery?
  3. for EACH tracked account: is it discoverable (Business/Creator), and do
     its videos come back with a media_url?

The third question decides the architecture: an account without media_url
gives metadata + captions through the official API, but the video itself —
and therefore the transcription — still needs another path. This command
measures it instead of assuming it either way.

Read-only: nothing is written except (with --save) the discoverability
verdict on each TrackedAccount and the resolved caller id printed for .env.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.models import TrackedAccount


class Command(BaseCommand):
    help = "Verifica token, chiamante e discoverability di ogni account (Graph API)."

    def add_arguments(self, parser):
        parser.add_argument("--save", action="store_true",
                            help="Registra il verdetto su ogni TrackedAccount "
                                 "(scrape_state.graph_not_discoverable).")

    def handle(self, *args, **opts):
        from scraper import graph_client

        if not graph_client.configured():
            raise CommandError(
                "IG_GRAPH_TOKEN non configurato in .env.\n"
                "Passi manuali: docs/instagram-graph-api-setup.md")

        # 1. il token
        try:
            me = graph_client.whoami()
        except graph_client.GraphError as exc:
            raise CommandError(f"Token non valido: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(
            f"Token OK — identità: {me.get('name')} (id {me.get('id')})"))

        # 2. il chiamante
        from django.conf import settings
        caller = settings.IG_GRAPH_USER_ID
        if caller:
            self.stdout.write(f"Caller IG (da .env): {caller}")
        else:
            try:
                caller = graph_client.resolve_caller_ig_id()
            except graph_client.GraphError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(self.style.WARNING(
                f"Caller IG risolto: {caller} — aggiungi a .env: "
                f"IG_GRAPH_USER_ID={caller}"))

        # 3. gli account, uno per uno
        self.stdout.write("\nAccount tracciati:")
        ok = no = 0
        for account in TrackedAccount.objects.filter(is_active=True).order_by(
                "owner_type", "username"):
            r = graph_client.probe(account.username, caller)
            if r["discoverable"]:
                ok += 1
                urls = f"{r['with_media_url']}/{r['videos_sampled']} video con media_url"
                mark = self.style.SUCCESS("✓")
                extra = f"{r.get('followers') or '?'} follower · {urls}"
                if opts["save"]:
                    state = dict(account.scrape_state or {})
                    state.pop("graph_not_discoverable", None)
                    account.scrape_state = state
                    account.save(update_fields=["scrape_state"])
            else:
                no += 1
                mark = self.style.ERROR("✗")
                extra = f"NON discoverable — {r['reason']}"
                if opts["save"]:
                    account.scrape_state = {
                        **(account.scrape_state or {}),
                        "graph_not_discoverable": r["reason"],
                    }
                    account.save(update_fields=["scrape_state"])
            self.stdout.write(
                f"  {mark} {account.owner_type:11} @{account.username:34} {extra}")

        self.stdout.write(
            f"\n{ok} interrogabili, {no} no. "
            + ("Verdetti salvati." if opts["save"] else
               "Rilancia con --save per registrare i verdetti."))
        if ok:
            self.stdout.write(self.style.SUCCESS(
                "\nLa raccolta ripartirà da sola alla prossima pipeline "
                "(lo stage scrape usa il provider 'graph' quando il token è "
                "configurato)."))
