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
from .models import CollectionRule, CollectionPeriod, InterestCondition
from .conditions import condition_id
from .period import selection, months_before
from .service import central_alias, enqueue_rule


class ConditionForm(forms.Form):
    kind = forms.ChoiceField(label="관심조건 종류", choices=InterestCondition._meta.get_field("kind").choices)
    key = forms.SlugField(label="안정적인 조건 키", max_length=120)
    name = forms.CharField(label="업종명 / 키워드", max_length=255)


class RuleForm(forms.Form):
    condition = forms.ModelChoiceField(label="연결할 논리 관심조건", queryset=InterestCondition.objects.none(),
                                       widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['condition'].queryset = InterestCondition.objects.using(central_alias()).order_by('kind', 'name')

    def clean(self):
        data = super().clean()
        condition = data.get('condition')
        if condition and condition.kind != data.get('kind'):
            raise forms.ValidationError('관심조건과 기관별 규칙의 종류가 다릅니다.')
        return data

    source = forms.ChoiceField(label="공고 출처", required=False, choices=CollectionRule._meta.get_field("source").choices, initial="g2b", widget=forms.Select(attrs={"class": "form-select"}))
    kind = forms.ChoiceField(label="조건 종류", choices=CollectionRule._meta.get_field("kind").choices,
                             widget=forms.Select(attrs={"class": "form-select"}))
    value = forms.CharField(label="나라장터 업종코드 / 한전 참가자격 업종명 / 공고명 키워드", max_length=120,
                            widget=forms.TextInput(attrs={"class": "form-control"}))
    name = forms.CharField(label="표시 이름", max_length=255,
                           widget=forms.TextInput(attrs={"class": "form-control"}))

    def clean_value(self):
        value = self.cleaned_data["value"].strip()
        if (self.cleaned_data.get("source") or "g2b") == "g2b" and self.cleaned_data.get("kind") == "industry" and not (value.isascii() and value.isdigit()):
            raise forms.ValidationError("나라장터 숫자 업종코드를 입력하세요.")
        return value


class PeriodForm(forms.Form):
    start_date = forms.DateField(label="수집 시작일", required=False,
                                widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"))
    end_date = forms.DateField(label="수집 종료일", required=False,
                              widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"))
    preset = forms.ChoiceField(required=False, choices=[("", "직접 지정")] + [(str(n), str(n)) for n in (1, 3, 6, 12, 24)], widget=forms.HiddenInput)

    def clean(self):
        data = super().clean()
        scope = selection()
        if data.get("preset"):
            data["end_date"] = scope["maximum_date"]
            data["start_date"] = months_before(data["end_date"], int(data["preset"]))
        start, end = data.get("start_date"), data.get("end_date")
        if not start or not end:
            raise forms.ValidationError("시작일과 종료일을 입력하세요.")
        if not scope["minimum_date"] <= start <= end <= scope["maximum_date"]:
            raise forms.ValidationError("최근 2년 이내에서 시작일 ≤ 종료일 ≤ 오늘 순서로 입력하세요.")
        return data


@require_central_admin
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def dashboard(request):
    form = RuleForm()
    condition_form = ConditionForm()
    period_form = PeriodForm(initial=selection())
    alias = central_alias()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_condition":
            condition_form = ConditionForm(request.POST)
            if condition_form.is_valid():
                data = condition_form.cleaned_data
                _, created = InterestCondition.objects.using(alias).get_or_create(
                    kind=data['kind'], key=data['key'],
                    defaults={'id': condition_id(data['kind'], data['key']), 'name': data['name']})
                if created:
                    return redirect("control:central_bids")
                condition_form.add_error('key', '이미 등록된 관심조건 키입니다.')
        elif action == "set_period":
            period_form = PeriodForm(request.POST)
            if period_form.is_valid():
                with transaction.atomic(using=alias):
                    CollectionPeriod.objects.using(alias).update_or_create(pk=1, defaults={
                        "start_date": period_form.cleaned_data["start_date"],
                        "end_date": period_form.cleaned_data["end_date"]})
                return redirect("control:central_bids")
        elif action == "create":
            form = RuleForm(request.POST)
            if form.is_valid():
                with transaction.atomic(using=alias):
                    rule, created = CollectionRule.objects.using(alias).get_or_create(
                        source=form.cleaned_data.get("source") or "g2b", kind=form.cleaned_data["kind"], value=form.cleaned_data["value"],
                        defaults={"name": form.cleaned_data["name"], "condition": form.cleaned_data["condition"]})
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
                    was_active = rule.active
                    if action in {"enable", "disable"}:
                        rule.active = action == "enable"
                        rule.save(using=alias, update_fields=["active"])
                    if rule.active:
                        if action == "enable" and not was_active:
                            from .lifecycle import reactivate
                            reactivate(rule)
                        else:
                            enqueue_rule(rule)
            return redirect("control:central_bids")
        else:
            return HttpResponseBadRequest("지원하지 않는 작업입니다.")
    return render(request, "procurement/central_dashboard.html", {"form": form, "condition_form": condition_form, "period_form": period_form, **snapshot()})


@require_central_admin
@never_cache
@require_GET
def status(request):
    return JsonResponse({"html": render_to_string("procurement/central_status.html", snapshot(), request=request)})
