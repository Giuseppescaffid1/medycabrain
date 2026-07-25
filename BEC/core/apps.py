import sys

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        """Warm the sentence-transformers model in the web process only.

        Loading it costs ~14s. Paying that lazily on a user's first search
        would make that request feel broken, so the web worker loads it in a
        background thread at startup. Management commands (jobs, pipeline)
        must NOT warm it: short-lived job processes are handed their query
        vector precomputed, which is the whole point.
        """
        if not any("gunicorn" in str(a) for a in sys.argv):
            return

        import threading

        def _warm():
            try:
                from core.knowledge import _get_embedder
                _get_embedder()
            except Exception:  # noqa: BLE001 — warming is best-effort
                pass

        threading.Thread(target=_warm, daemon=True).start()
