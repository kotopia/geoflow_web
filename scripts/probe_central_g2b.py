"""No production settings, DB, SSH, or filesystem secret files are loaded."""
import os
import sys
from pathlib import Path


def main():
    if os.environ.get("G2B_PROBE_APPROVED") != "1":
        print('{"ok":false,"code":"PROBE_NOT_ENABLED"}')
        return 2
    key = os.environ.get("G2B_API_SERVICE_KEY", "").strip()
    if not key:
        print('{"ok":false,"code":"MISSING_SERVICE_KEY"}')
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from django.conf import settings
    if settings.configured or os.environ.get("DJANGO_SETTINGS_MODULE"):
        print('{"ok":false,"code":"NON_ISOLATED_SETTINGS"}')
        return 2
    settings.configure(
        SECRET_KEY="disposable-g2b-probe", INSTALLED_APPS=["procurement"],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        CENTRAL_DB_ALIAS="default", USE_TZ=True, TIME_ZONE="Asia/Seoul",
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        G2B_API_SERVICE_KEY=key, G2B_CENTRAL_DAILY_BUDGET=9,
    )
    import django
    django.setup()
    from django.core.management import call_command
    from django.utils import timezone
    from procurement.live_probe import run_probe
    try:
        call_command("migrate", "procurement", verbosity=0)
        return 0 if run_probe(timezone.now()) else 1
    except Exception:
        # Never print exception tracebacks from a secret-bearing live request.
        print('{"ok":false,"code":"PROBE_INTERNAL_ERROR"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
