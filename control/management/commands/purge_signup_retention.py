from django.core.management.base import BaseCommand, CommandError

from control.services.signup_retention_service import purge_terminal_signup_data


class Command(BaseCommand):
    help = (
        "Review or purge rejected/expired signup-only identities after the one-year "
        "retention period. Dry-run is the default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually purge eligible records. Omit for dry-run.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Maximum number of candidates to inspect/purge (1-500).",
        )

    def handle(self, *args, **options):
        try:
            result = purge_terminal_signup_data(
                execute=bool(options["execute"]),
                batch_size=int(options["batch_size"]),
            )
        except (ValueError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc

        if result.dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"dry-run only: eligible_candidates={result.candidates}; purged=0"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"retention purge complete: candidates={result.candidates}; "
                f"purged={result.purged}"
            )
        )
