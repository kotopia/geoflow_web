from django.contrib import admin
from django.core.exceptions import ValidationError
from django import forms

from .models import CollectionJob, CollectionRule
from .service import central_alias, enqueue_rule


class RuleForm(forms.ModelForm):
    class Meta:
        model = CollectionRule
        fields = ("kind", "value", "name", "active")

    def clean(self):
        data = super().clean()
        value = str(data.get("value") or "").strip()
        if not value or (data.get("kind") == "industry" and not value.isascii()) or (
            data.get("kind") == "industry" and not value.isdigit()
        ):
            raise ValidationError("업종은 나라장터 숫자 코드를, 키워드는 공고명 검색어를 입력하세요.")
        data["value"] = value
        return data


class CentralAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    has_add_permission = has_view_permission
    has_change_permission = has_view_permission

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).using(central_alias())


@admin.register(CollectionRule)
class RuleAdmin(CentralAdmin):
    form = RuleForm
    list_display = ("name", "kind", "value", "active", "created_at")

    def get_readonly_fields(self, request, obj=None):
        return ("kind", "value") if obj else ()

    def save_model(self, request, obj, form, change):
        # Changed search semantics require a new rule; old provenance stays intact.
        from django.db import transaction
        with transaction.atomic(using=central_alias()):
            obj.save(using=central_alias())
            if obj.active:
                enqueue_rule(obj)


@admin.register(CollectionJob)
class JobAdmin(CentralAdmin):
    list_display = ("rule", "status", "backfill_cursor", "backfill_end", "live_cursor", "last_success_at", "error_code")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
