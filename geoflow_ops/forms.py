from __future__ import annotations
from django import forms
from .models import Contract, Partner, Project, MyOrgUnit
from control.middleware import current_db_alias
from .services.tenant_settings import (
    CONTRACT_KIND_FALLBACK,
    CONTRACT_STATUS_FALLBACK,
    normalize_contract_status,
    settings_options,
)

STATUS_CHOICES = list(CONTRACT_STATUS_FALLBACK)
KIND_CHOICES = list(CONTRACT_KIND_FALLBACK)


class ISODateInput(forms.DateInput):
    input_type = "text"
    format = "%Y-%m-%d"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("format", self.format)
        super().__init__(*args, **kwargs)
        self.is_localized = False
        self.attrs.setdefault("placeholder", "YYYY-MM-DD")
        self.attrs.setdefault("inputmode", "numeric")
        self.attrs.setdefault("pattern", "[0-9]*")


class ContractForm(forms.ModelForm):
    # Kept for tenant vocabulary/backward compatibility, but lifecycle is
    # event-driven. Users do not manually move 계약 -> 진행 -> 준공 here.
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False, disabled=True)
    kind = forms.ChoiceField(choices=KIND_CHOICES, required=False)

    start_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%Y%m%d"],
        widget=ISODateInput(),
        localize=False,
    )
    end_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%Y%m%d"],
        widget=ISODateInput(),
        localize=False,
    )

    class Meta:
        model = Contract
        fields = [
            "code", "name", "start_date", "end_date",
            "amount", "status", "kind", "division",
            "client", "sub_client", "org_unit", "description",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "start_date": forms.TextInput(attrs={"class": "form-control"}),
            "end_date": forms.TextInput(attrs={"class": "form-control"}),
            "kind": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control"}),
            "client": forms.Select(attrs={"class": "form-select"}),
            "sub_client": forms.Select(attrs={"class": "form-select"}),
            "org_unit": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        alias = current_db_alias()

        def _partner_label(p):
            name = getattr(p, "name", "") or str(p)
            partner_type = getattr(p, "type", None) or getattr(p, "kind", None)
            return f"{name} ({partner_type})" if partner_type else name

        self.fields["start_date"].required = False
        self.fields["end_date"].required = False

        status_choices = list(settings_options(alias, "contract.status"))
        kind_choices = list(settings_options(alias, "contract.kind"))

        current_status = normalize_contract_status(getattr(self.instance, "status", "")) or "planned"
        if current_status and current_status not in {code for code, _ in status_choices}:
            status_choices.append((current_status, f"{current_status} (기존값)"))
        current_kind = str(getattr(self.instance, "kind", "") or "").strip()
        if current_kind and current_kind not in {code for code, _ in kind_choices}:
            kind_choices.append((current_kind, f"{current_kind} (기존값)"))

        self.fields["status"] = forms.ChoiceField(
            choices=[("", "---------"), *status_choices], required=False, disabled=True
        )
        self.fields["kind"] = forms.ChoiceField(
            choices=[("", "---------"), *kind_choices], required=False
        )
        self.fields["status"].widget.attrs.update({
            "class": "form-select",
            "aria-readonly": "true",
            "title": "업무단계는 이벤트에서 자동 변경됩니다.",
        })
        self.fields["kind"].widget.attrs.update({"class": "form-select"})

        self.initial["status"] = current_status
        if current_kind:
            self.initial["kind"] = current_kind

        if "client" in self.fields:
            self.fields["client"].queryset = Partner.objects.using(alias).all().order_by("name")
            self.fields["client"].label_from_instance = _partner_label
        if "sub_client" in self.fields:
            self.fields["sub_client"].queryset = Partner.objects.using(alias).all().order_by("name")
            self.fields["sub_client"].label_from_instance = _partner_label

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip()
        if not code:
            raise forms.ValidationError("계약번호를 입력하세요.")
        alias = current_db_alias()
        qs = Contract.objects.using(alias).filter(code=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"이미 사용 중인 계약번호입니다: {code}")
        return code

    def clean_status(self):
        return normalize_contract_status(self.cleaned_data.get("status"))

    def clean(self):
        cd = super().clean()
        status = normalize_contract_status(cd.get("status"))
        cd["status"] = status
        sdate = cd.get("start_date")
        edate = cd.get("end_date")

        if status == "active" and not sdate:
            self.add_error("start_date", "진행 상태는 시작일이 필요합니다.")
        if status == "complete":
            if not sdate:
                self.add_error("start_date", "완료 상태는 시작일이 필요합니다.")
            if not edate:
                self.add_error("end_date", "완료 상태는 종료일이 필요합니다.")

        if sdate and edate and edate < sdate:
            self.add_error("end_date", "종료일은 시작일 이후여야 합니다.")
        return cd


class PartnerForm(forms.ModelForm):
    class Meta:
        model = Partner
        fields = [
            "name", "type", "biz_no", "rep_name",
            "phone", "email", "address",
            "status", "description",
        ]


class ProjectForm(forms.ModelForm):
    start_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%Y%m%d"],
        widget=ISODateInput(),
    )
    end_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%Y%m%d"],
        widget=ISODateInput(),
    )

    class Meta:
        model = Project
        fields = [
            "contract", "code", "name",
            "start_date", "end_date",
            "status", "description", "org_unit_id",
        ]


class ProjectNoteForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["description"]


class MyOrgUnitForm(forms.ModelForm):
    class Meta:
        model = MyOrgUnit
        fields = [
            "name", "type", "biz_no", "rep_name", "phone", "email",
            "address", "label", "description",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.TextInput(attrs={"class": "form-control"}),
            "biz_no": forms.TextInput(attrs={"class": "form-control"}),
            "rep_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "label": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }
        