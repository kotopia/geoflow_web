from django import forms
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods

from control.decorators import require_central_admin
from .dashboard import snapshot
from .models import CollectionRule
from .service import central_alias, enqueue_rule


class RuleForm(forms.Form):
    kind = forms.ChoiceField(label="조건 종류", choices=CollectionRule._meta.get_field("kind").choices,
                             widget=forms.Select(attrs={"class": "form-select"}))
    value = forms.CharField(label="나라장터 업종코드 또는 키워드", max_length=120,
                            widget=forms.TextInput(attrs={"class": "form-control"}))
    name = forms.CharField(label="표시 이름", max_length=255,
                           widget=forms.TextInput(attrs={"class": "form-control"}))

    def clean_value(self):
        value = self.cleaned_data["value"].strip()
        if self.cleaned_data.get("kind") == "industry" and not (value.isascii() and value.isdigit()):
            raise forms.ValidationError("나라장터 숫자 업종코드를 입력하세요.")
        return value


@require_central_admin
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def dashboard(request):
    form = RuleForm()
    alias = central_alias()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            form = RuleForm(request.POST)
            if form.is_valid():
                with transaction.atomic(using=alias):
                    rule, created = CollectionRule.objects.using(alias).get_or_create(
                        kind=form.cleaned_data["kind"], value=form.cleaned_data["value"],
                        defaults={"name": form.cleaned_data["name"]})
                    if created:
                        enqueue_rule(rule)
                if created:
                    return redirect("control:central_bids")
                form.add_error("value", "이미 등록된 조건입니다. 기존 조건을 확인하세요.")
        elif action in {"sync_all", "sync", "enable", "disable"}:
            with transaction.atomic(using=alias):
                rules = CollectionRule.objects.using(alias).select_for_update()
                if action == "sync_all":
                    for rule in rules.filter(active=True):
                        enqueue_rule(rule)
                else:
                    # Parse with a form field so malformed identifiers return 400, not 500.
                    try:
                        rule_id = forms.UUIDField().clean(request.POST.get("rule_id"))
                    except forms.ValidationError:
                        return HttpResponseBadRequest("수집조건을 확인하세요.")
                    rule = get_object_or_404(rules, pk=rule_id)
                    if action in {"enable", "disable"}:
                        rule.active = action == "enable"
                        rule.save(using=alias, update_fields=["active"])
                    if rule.active:
                        enqueue_rule(rule)
            return redirect("control:central_bids")
        else:
            return HttpResponseBadRequest("지원하지 않는 작업입니다.")
    return render(request, "procurement/central_dashboard.html", {"form": form, **snapshot()})


@require_central_admin
@never_cache
@require_GET
def status(request):
    return JsonResponse({"html": render_to_string("procurement/central_status.html", snapshot(), request=request)})
