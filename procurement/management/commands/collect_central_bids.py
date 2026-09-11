from django.core.management.base import BaseCommand, CommandError
from procurement.service import run_worker


class Command(BaseCommand):
    help = "중앙 입찰 대기작업을 제한된 호출 예산 내에서 실행합니다."

    def add_arguments(self, parser):
        parser.add_argument("--request-budget", type=int, default=100)
        parser.add_argument("--max-steps", type=int, default=10)

    def handle(self, **options):
        budget, steps = options["request_budget"], options["max_steps"]
        if not 1 <= budget <= 1000 or not 1 <= steps <= 100:
            raise CommandError("호출예산 1~1000, 작업수 1~100 범위가 필요합니다.")
        completed = run_worker(budget, steps)
        self.stdout.write(f"Completed windows: {completed}")
