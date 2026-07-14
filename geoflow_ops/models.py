# geoflow_ops/models.py
import uuid
from django.db import models
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField, CIEmailField, JSONField  # Django 5.1 OK

# =========================
# 파트너 (ctr.partners)
# =========================
class Partner(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    legacy_id = models.BigIntegerField(null=True, db_column="legacy_id", blank=True)
    name = models.TextField(db_column="name")
    type = models.TextField(db_column="type", blank=True, null=True)     # 발주처/하도급 등
    biz_no = models.TextField(db_column="biz_no", blank=True, null=True)
    rep_name = models.TextField(db_column="rep_name", blank=True, null=True)
    phone = models.TextField(db_column="phone", blank=True, null=True)
    email = models.TextField(db_column="email", blank=True, null=True)   # citext도 Text로 OK
    address = models.TextField(db_column="address", blank=True, null=True)
    status = models.TextField(db_column="status", blank=True, null=True)
    description = models.TextField(db_column="description", blank=True, null=True)
    created_at = models.DateTimeField(db_column="created_at", null=True, blank=True)
    updated_at = models.DateTimeField(db_column="updated_at", null=True, blank=True)

    class Meta:
        db_table = '"ctr"."partners"'
        managed = False


# =========================
# 계약 (ctr.contracts)
# =========================
class Contract(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # contracts.id
    legacy_id = models.BigIntegerField(db_column="legacy_id", null=True, blank=True)
    code = models.TextField(db_column="code", blank=True, null=True)     # 계약번호 (수정 가능)
    name = models.TextField(db_column="name")
    start_date = models.DateField(db_column="start_date", null=True, blank=True)
    end_date = models.DateField(db_column="end_date", null=True, blank=True)
    amount = models.DecimalField(db_column="amount", max_digits=14, decimal_places=0, null=True, blank=True)
    status = models.TextField(db_column="status", blank=True, null=True) # '계약체결' 등
    kind = models.TextField(db_column="kind", blank=True, null=True)     # type과 유사: 필요시 사용
    division = models.TextField(db_column="division", blank=True, null=True)

    client = models.ForeignKey(
        Partner, db_column="client_id", related_name="contracts_as_owner",
        on_delete=models.PROTECT, null=True, blank=True
    )
    sub_client = models.ForeignKey(
        Partner, db_column="sub_client_id", related_name="contracts_as_sub",
        on_delete=models.PROTECT, null=True, blank=True
    )
    
    # 🔹 계약 당사자(우리 회사 본사/지사)
    org_unit = models.ForeignKey(
        "MyOrgUnit",
        db_column="org_unit_id",        # DB 컬럼 이름은 그대로 사용
        related_name="contracts",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    
    ext = models.JSONField(db_column="ext", null=True, blank=True)

    created_at = models.DateTimeField(db_column="created_at", null=True, blank=True)
    updated_at = models.DateTimeField(db_column="updated_at", null=True, blank=True)

    description = models.TextField("비고", blank=True, null=True)

    class Meta:
        db_table = '"ctr"."contracts"'
        managed = False


# =========================
# 프로젝트 (prj.projects)
# =========================
class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(
        Contract, db_column="contract_id", related_name="project_set",
        on_delete=models.CASCADE, null=True, blank=True
    )
    code = models.TextField(db_column="code", blank=True, null=True)
    name = models.TextField(db_column="name", blank=True, null=True)
    start_date = models.DateField(db_column="start_date", null=True, blank=True)
    end_date = models.DateField(db_column="end_date", null=True, blank=True)
    status = models.TextField(db_column="status", blank=True, null=True)
    description = models.TextField(db_column="description", blank=True, null=True)

    # ⬇ 외래키 대신 UUID 그대로 (DB 컬럼을 그대로 매핑)
    org_unit_id = models.UUIDField(db_column="org_unit_id", null=True, blank=True)

    ext = models.JSONField(db_column="ext", null=True, blank=True)
    created_at = models.DateTimeField(db_column="created_at", null=True, blank=True)
    updated_at = models.DateTimeField(db_column="updated_at", null=True, blank=True)

    class Meta:
        db_table = '"prj"."projects"'
        managed = False

# =========================
# 우리 회사 본사/지사 (ops.my_org_units)
# =========================
class MyOrgUnit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField(db_column="name")                     # 본사, 천안지사 등
    type = models.TextField(db_column="type", blank=True, null=True)
    biz_no = models.TextField(db_column="biz_no", blank=True, null=True)
    rep_name = models.TextField(db_column="rep_name", blank=True, null=True)
    phone = models.TextField(db_column="phone", blank=True, null=True)
    email = models.TextField(db_column="email", blank=True, null=True)
    address = models.TextField(db_column="address", blank=True, null=True)
    label = models.TextField(db_column="label", blank=True, null=True)
    description = models.TextField(db_column="description", blank=True, null=True)
    created_at = models.DateTimeField(db_column="created_at", null=True, blank=True)
    updated_at = models.DateTimeField(db_column="updated_at", null=True, blank=True)

    created_at = models.DateTimeField(db_column="created_at",
                                      default=timezone.now, blank=True, null=True)
    updated_at = models.DateTimeField(db_column="updated_at",
                                      default=timezone.now, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.created_at:
            self.created_at = timezone.now()
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        db_table = '"ops"."my_org_units"'
        managed = False


# =========================
# 카테고리 (prj.scope_item)
# =========================

class ProjectScopeItem(models.Model):
    """
    프로젝트별 카테고리(L2~L4) 업무범위 정의 테이블
    - 한 행 = 프로젝트 + (Lv2~Lv4 조합) + 수량 + 단위
    - Lv1은 중앙 카탈로그에서 lv2_id의 부모로 항상 계산 가능하므로 여기서는 보관하지 않음
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_column="id",
    )

    project_id = models.UUIDField(
        db_column="project_id",
        help_text="프로젝트 ID (prj.projects.id)",
    )

    # 중앙 카탈로그 CategoryNode / CategoryFacetOption 의 UUID
    lv2_id = models.UUIDField(
        db_column="lv2_id",
        help_text="L2(CategoryNode.id) - 중분류",
    )
    lv3_id = models.UUIDField(
        null=True,
        blank=True,
        db_column="lv3_id",
        help_text="L3(CategoryFacetOption.id) - 세분류(옵션)",
    )
    lv4_id = models.UUIDField(
        null=True,
        blank=True,
        db_column="lv4_id",
        help_text="L4(CategoryFacetOption.id) - 세분류(옵션)",
    )

    unit = models.CharField(
        max_length=20,
        db_column="unit",
        help_text="단위 코드 (예: m, EA, ㎡ 등)",
    )

    design_qty = models.DecimalField(
        max_digits=18,
        decimal_places=3,
        null=True,
        blank=True,
        db_column="design_qty",
        help_text="설계 수량/연장",
    )

    completed_qty = models.DecimalField(
        max_digits=18,
        decimal_places=3,
        null=True,
        blank=True,
        db_column="completed_qty",
        help_text="완료(실적) 수량/연장",
    )

    remark = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_column="remark",
        help_text="간단한 메모",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_column="created_at",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_column="updated_at",
    )

    class Meta:
        # PostgreSQL 스키마 사용: prj.scope_item
        db_table = '"prj"."scope_item"'
        managed = False  # 테이블은 직접 생성/관리

    def __str__(self):
        return f"{self.project_id} / {self.lv2_id} ({self.unit}, {self.design_qty or 0})"


# =========================
# 첨부파일 (ops.attachments)
# =========================
class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column="id")
    entity_type = models.TextField(db_column="entity_type")
    entity_id = models.UUIDField(db_column="entity_id")
    purpose = models.TextField(db_column="purpose")

    object_key = models.TextField(db_column="object_key", unique=True)
    original_name = models.TextField(db_column="original_name")
    mime_type = models.TextField(db_column="mime_type", blank=True, null=True)
    size_bytes = models.BigIntegerField(db_column="size_bytes", null=True, blank=True)
    sha256 = models.TextField(db_column="sha256", blank=True, null=True)

    active = models.BooleanField(db_column="active", default=True)
    ord = models.IntegerField(db_column="ord", default=0)
    meta = models.JSONField(db_column="meta", default=dict, blank=True)

    created_at = models.DateTimeField(db_column="created_at", auto_now_add=True)
    updated_at = models.DateTimeField(db_column="updated_at", auto_now=True)

    deleted_at = models.DateTimeField(db_column="deleted_at", null=True, blank=True)
    deleted_by = models.TextField(db_column="deleted_by", null=True, blank=True)
    is_deleted = models.BooleanField(db_column="is_deleted", default=False)

    kind = models.TextField(db_column="kind", default="file")
    parent = models.ForeignKey(
        "self",
        db_column="parent_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="derivatives",
    )

    class Meta:
        db_table = '"ops"."attachments"'
        managed = True
        indexes = [
            models.Index(fields=["entity_type", "entity_id"], name="idx_att_entity"),
            models.Index(fields=["entity_type", "entity_id", "purpose", "ord"], name="idx_att_entity_purpose_ord"),
        ]


# =========================
# 업무 프로세스 이벤트 (ops.process_events)
# =========================
class ProcessEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column="id")
    scope_type = models.CharField(max_length=50, db_column="scope_type")
    scope_id = models.UUIDField(db_column="scope_id")
    stage = models.CharField(max_length=50, db_column="stage")
    event_type = models.CharField(max_length=50, db_column="event_type")

    title = models.CharField(max_length=255, db_column="title", default="", blank=True)
    memo = models.TextField(db_column="memo", blank=True, default="")

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("open", "Open"),
        ("done", "Done"),
        ("void", "Void"),
    ]
    status = models.CharField(max_length=20, db_column="status", choices=STATUS_CHOICES, default="draft")

    occurred_at = models.DateField(db_column="occurred_at", null=True, blank=True)
    due_at = models.DateField(db_column="due_at", null=True, blank=True)

    created_by = models.CharField(max_length=255, db_column="created_by")
    created_at = models.DateTimeField(db_column="created_at", auto_now_add=True)
    updated_at = models.DateTimeField(db_column="updated_at", auto_now=True)

    class Meta:
        db_table = '"ops"."process_events"'
        managed = True
        indexes = [
            models.Index(fields=["scope_type", "scope_id"], name="idx_event_scope"),
            models.Index(fields=["scope_type", "scope_id", "stage"], name="idx_event_scope_stage"),
            models.Index(fields=["status"], name="idx_event_status"),
        ]


# =========================
# 프로세스 이벤트-첨부 링크 (ops.process_event_attachments)
# =========================
class ProcessEventAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_column="id")

    event = models.ForeignKey(
        ProcessEvent,
        db_column="event_id",
        on_delete=models.CASCADE,
        related_name="attachment_links",
    )
    attachment = models.ForeignKey(
        Attachment,
        db_column="attachment_id",
        on_delete=models.CASCADE,
        related_name="event_links",
    )

    ROLE_CHOICES = [
        ("primary", "Primary"),
        ("support", "Support"),
    ]
    role = models.CharField(max_length=20, db_column="role", choices=ROLE_CHOICES, default="support")
    ord = models.PositiveIntegerField(db_column="ord", default=0)
    created_at = models.DateTimeField(db_column="created_at", auto_now_add=True)

    class Meta:
        db_table = '"ops"."process_event_attachments"'
        managed = True
        constraints = [
            models.UniqueConstraint(fields=["event", "attachment"], name="unique_event_attachment"),
        ]
        indexes = [
            models.Index(fields=["event", "ord"], name="idx_event_att_ord"),
        ]
    

