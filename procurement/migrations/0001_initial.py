import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="ApiBudget", fields=[
            ("day", models.DateField(primary_key=True, serialize=False)),
            ("used", models.PositiveIntegerField(default=0)),
        ]),
        migrations.CreateModel(name="CollectionRule", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("kind", models.CharField(max_length=16, choices=[("industry", "업종코드"), ("keyword", "공고명 키워드")])),
            ("value", models.CharField(max_length=120)), ("name", models.CharField(max_length=255)),
            ("active", models.BooleanField(default=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
        ], options={"verbose_name": "중앙 수집조건", "verbose_name_plural": "중앙 수집조건",
                    "constraints": [models.UniqueConstraint(fields=("kind", "value"), name="procurement_rule_unique")]}),
        migrations.CreateModel(name="CollectionJob", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("backfill_cursor", models.DateTimeField()), ("backfill_end", models.DateTimeField()),
            ("live_cursor", models.DateTimeField()), ("due_at", models.DateTimeField()),
            ("requested", models.BooleanField(default=False)), ("status", models.CharField(max_length=20, default="pending")),
            ("last_success_at", models.DateTimeField(null=True, blank=True)),
            ("error_code", models.CharField(max_length=100, blank=True)), ("fetched_count", models.PositiveIntegerField(default=0)),
            ("rule", models.OneToOneField(to="procurement.collectionrule", on_delete=django.db.models.deletion.PROTECT)),
        ], options={"verbose_name": "수집 진행상태", "verbose_name_plural": "수집 진행상태"}),
        migrations.CreateModel(name="Notice", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("number", models.CharField(max_length=80)), ("order", models.CharField(max_length=20)),
            ("title", models.TextField()), ("posted_at", models.DateTimeField(db_index=True)),
            ("close_at", models.DateTimeField(null=True, db_index=True)),
            ("agency", models.CharField(max_length=255, blank=True)), ("demand_agency", models.CharField(max_length=255, blank=True)),
            ("estimated_price", models.DecimalField(max_digits=20, decimal_places=0, null=True, db_index=True)),
            ("region_text", models.TextField(blank=True)), ("industry_text", models.TextField(blank=True)),
            ("region_known", models.BooleanField(default=False)), ("industry_known", models.BooleanField(default=False)),
            ("summary", models.JSONField(default=dict)), ("raw", models.JSONField(default=dict)),
            ("payload_hash", models.CharField(max_length=64)), ("source_updated_at", models.DateTimeField(null=True)),
            ("last_seen_at", models.DateTimeField()),
            ("rules", models.ManyToManyField(to="procurement.collectionrule", related_name="notices")),
        ]),
        migrations.CreateModel(name="NoticeRevision", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("payload_hash", models.CharField(max_length=64)), ("raw", models.JSONField()),
            ("captured_at", models.DateTimeField(auto_now_add=True)),
            ("notice", models.ForeignKey(to="procurement.notice", on_delete=django.db.models.deletion.CASCADE)),
        ]),
        migrations.AddIndex(model_name="notice", index=models.Index(fields=["-posted_at", "id"], name="procurement_notice_page_idx")),
        migrations.AddConstraint(model_name="notice", constraint=models.UniqueConstraint(fields=("number", "order"), name="procurement_notice_unique")),
        migrations.AddConstraint(model_name="noticerevision", constraint=models.UniqueConstraint(fields=("notice", "payload_hash"), name="procurement_revision_unique")),
    ]
