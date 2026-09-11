import uuid

from django.db import models


class CollectionRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=[("industry", "업종코드"), ("keyword", "공고명 키워드")])
    value = models.CharField(max_length=120)
    name = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "value"], name="procurement_rule_unique")]
        verbose_name = "중앙 수집조건"
        verbose_name_plural = "중앙 수집조건"

    def __str__(self):
        return self.name


class CollectionJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.OneToOneField(CollectionRule, on_delete=models.PROTECT)
    # Backfill and ongoing refresh have independent durable checkpoints.
    backfill_cursor = models.DateTimeField()
    backfill_end = models.DateTimeField()
    live_cursor = models.DateTimeField()
    due_at = models.DateTimeField()
    requested = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default="pending")
    last_success_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    fetched_count = models.PositiveIntegerField(default=0)
    progress = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "수집 진행상태"
        verbose_name_plural = "수집 진행상태"


class Notice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=80)
    order = models.CharField(max_length=20)
    title = models.TextField()
    posted_at = models.DateTimeField(db_index=True)
    close_at = models.DateTimeField(null=True, db_index=True)
    agency = models.CharField(max_length=255, blank=True)
    demand_agency = models.CharField(max_length=255, blank=True)
    estimated_price = models.DecimalField(max_digits=20, decimal_places=0, null=True, db_index=True)
    region_text = models.TextField(blank=True)
    industry_text = models.TextField(blank=True)
    region_known = models.BooleanField(default=False)
    industry_known = models.BooleanField(default=False)
    summary = models.JSONField(default=dict)
    raw = models.JSONField(default=dict)
    payload_hash = models.CharField(max_length=64)
    source_updated_at = models.DateTimeField(null=True)
    last_seen_at = models.DateTimeField()
    rules = models.ManyToManyField(CollectionRule, related_name="notices")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["number", "order"], name="procurement_notice_unique")]
        indexes = [models.Index(fields=["-posted_at", "id"], name="procurement_notice_page_idx")]


class NoticeRevision(models.Model):
    notice = models.ForeignKey(Notice, on_delete=models.CASCADE)
    payload_hash = models.CharField(max_length=64)
    raw = models.JSONField()
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["notice", "payload_hash"], name="procurement_revision_unique")]


class ApiBudget(models.Model):
    day = models.DateField(primary_key=True)
    used = models.PositiveIntegerField(default=0)
