from __future__ import annotations
from django import forms
from .models import Contract, Partner, Project, MyOrgUnit
from control.middleware import current_db_alias
from .services.tenant_settings import settings_options
from .services.contract_project_pair import PROJECT_MODES, project_mode

KIND_CHOICES = []


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
    """Edit contract facts only; lifecycle is derived from milestone events."""

    project_mode = forms.ChoiceField(choices=PROJECT_MODES, label="프로젝트 운영방식", initial="SINGLE", widget=forms.Select(attrs={"class": "form-select"}))
    confirm_single = forms.BooleanField(required=False, label="단일 방식 전환 시 프로젝트명을 계약명으로 변경합니다.")
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
            "amount", "kind", "division",
            "client", "sub_client", "org_unit", "description",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control"}),
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
        self.initial["project_mode"] = (self.instance.ext or {}).get("project_mode", "SINGLE") if isinstance(self.instance.ext, (dict, type(None))) else ""

        def _partner_label(p):
            name = getattr(p, "name", "") or str(p)
            partner_type = getattr(p, "type", None) or getattr(p, "kind", None)
            return f"{name} ({partner_type})" if partner_type else name

        self.fields["start_date"].required = False
        self.fields["end_date"].required = False

        kind_choices = list(settings_options(alias, "contract.kind"))
        current_kind = str(getattr(self.instance, "kind", "") or "").strip()
        if current_kind and current_kind not in {code for code, _ in kind_choices}:
            kind_choices.append((current_kind, f"{current_kind} (기존값)"))

        self.fields["kind"] = forms.ChoiceField(
            choices=[("", "---------"), *kind_choices], required=False
        )
        self.fields["kind"].widget.attrs.update({"class": "form-select"})
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

    def clean(self):
        cd = super().clean()
        sdate = cd.get("start_date")
        edate = cd.get("end_date")
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
    confirm_duplicate = forms.BooleanField(required=False, label="같은 계약의 중복 이름을 확인했습니다.")
    status = forms.ChoiceField(required=False, label="수행상태")
    start_date = forms.DateField(required=False, input_formats=["%Y-%m-%d", "%Y%m%d"], widget=ISODateInput(), label="시작일")
    end_date = forms.DateField(required=False, input_formats=["%Y-%m-%d", "%Y%m%d"], widget=ISODateInput(), label="종료일")

    class Meta:
        model = Project
        fields = ["contract", "name", "start_date", "end_date", "status", "description"]
        labels = {"contract": "연결 계약", "name": "프로젝트명", "description": "기타사항"}

    def __init__(self, *args, alias, contracts=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .services.project_status import project_status_options
        self.fields["contract"].queryset = contracts if contracts is not None else Contract.objects.using(alias).none()
        self.fields["contract"].required = True
        self.fields["contract"].label_from_instance = lambda c: f"{c.code} · {c.name}"
        self.fields["status"].choices = [("", "미설정"), *project_status_options(alias)]
        current = self.instance.status
        if current and current not in dict(self.fields["status"].choices):
            self.fields["status"].choices.append((current, current + " (기존값)"))
        if not self.instance._state.adding:
            self.fields["contract"].queryset = Contract.objects.using(alias).filter(pk=self.instance.contract_id)
            self.fields["contract"].disabled = True
            if project_mode(self.instance.contract) == "SINGLE":
                self.fields["name"].disabled = True
                self.initial["name"] = self.instance.contract.name
                self.fields["name"].help_text = "계약명을 변경하면 함께 변경됩니다."
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else ("form-select" if isinstance(field.widget, forms.Select) else "form-control")

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "종료일은 시작일 이후여야 합니다.")
        contract = cleaned.get("contract")
        if contract and project_mode(contract) == "SINGLE":
            cleaned["name"] = contract.name
        elif contract and not str(cleaned.get("name") or "").strip():
            self.add_error("name", "프로젝트명을 입력하세요.")
        return cleaned


class MyOrgUnitForm(forms.ModelForm):
    class Meta:
        model = MyOrgUnit
        labels = {"name":"기업명", "type":"기존 구분", "biz_no":"사업자번호", "rep_name":"대표자", "phone":"전화", "email":"이메일", "address":"주소", "label":"별칭", "description":"비고"}
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
