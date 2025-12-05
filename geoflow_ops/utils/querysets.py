from django.db import models
from django.db.models import Q

class ProjectQuerySet(models.QuerySet):
    def with_contract(self):
        return self.select_related("contract")

    def ordered(self):
        return self.order_by("-created_at")

    def by_status(self, status: str | None):
        return self.filter(status=status) if status else self

    def search(self, term: str | None):
        if not term:
            return self
        return self.filter(
            Q(project_1__icontains=term) |
            Q(project_2__icontains=term) |
            Q(project_3__icontains=term) |
            Q(contract__contract_name__icontains=term) |
            Q(contract__contract_code__icontains=term)  # ← 모델 필드명과 일치
        )
