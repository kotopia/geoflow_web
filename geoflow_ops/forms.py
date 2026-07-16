from __future__ import annotations
from django import forms
from .models import Contract, Partner, Project, MyOrgUnit
from control.middleware import current_db_alias

STATUS_CHOICES = [
    ("planned", "계약전"),
    ("active", "진행"),
    ("completed", "완료"),
    ("cancel", "취소"),
    ("pause", "중지"),
]

KIND_CHOICES = [
    ("총액", "총액계약"),
    ("공동", "공동계약"),
    ("장기계속", "장기계속계약"),
    ("단가", "단가계약"),
    ("하도급", "하도급계약"),
]

class ISODateInput(forms.DateInput):
    input_type = "text"
    format = "%Y-%m-%d"

    def __init__(self, *args, **kwargs):
        # ✅ DateInput은 format만 받습니다. is_localized 인자 금지
        kwargs.setdefault("format", self.format)
        super().__init__(*args, **kwargs)
        # ✅ 로케일 표기 방지: 위젯 속성으로 지정
        self.is_localized = False

        # UX: 숫자 키패드/마스크와 잘 맞는 속성
        self.attrs.setdefault("placeholder", "YYYY-MM-DD")
        self.attrs.setdefault("inputmode", "numeric")
        self.attrs.setdefault("pattern", "[0-9]*")
        # (선택) 자동완성 방지
        # self.attrs.setdefault("autocomplete", "off")


class ContractForm(forms.ModelForm):
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False)
    kind = forms.ChoiceField(choices=KIND_CHOICES, required=False)

    # ✅ 필드에서 localize=False로 로케일 포맷 비활성화
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
            "client": forms.Select(attrs={"class": "form-select"}),      # Choices.js가 나중에 덮어씀
            "sub_client": forms.Select(attrs={"class": "form-select"}),  # 동일
            "org_unit": forms.Select(attrs={"class": "form-select"}),    # 🔹 우리 회사(본사/지사)
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        alias = current_db_alias()

        def _partner_label(p):
            name = getattr(p, "name", "") or str(p)
            partner_type = getattr(p, "type", None) or getattr(p, "kind", None)
            return f"{name} ({partner_type})" if partner_type else name

        # (명시 안 해도 위에서 required=False 지정했지만, 일관성 유지)
        self.fields["start_date"].required = False
        self.fields["end_date"].required = False

        # 상태 필드 재정의(기존 코드 유지)
        self.fields["status"] = forms.ChoiceField(choices=STATUS_CHOICES, required=False)

        # 파트너 선택은 테넌트 DB 기준으로
        if "client" in self.fields:
            self.fields["client"].queryset = Partner.objects.using(alias).all().order_by("name")
            self.fields["client"].label_from_instance = _partner_label
        if "sub_client" in self.fields:
            self.fields["sub_client"].queryset = Partner.objects.using(alias).all().order_by("name")
            self.fields["sub_client"].label_from_instance = _partner_label

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip()
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
        status = (cd.get("status") or "").strip()
        sdate  = cd.get("start_date")
        edate  = cd.get("end_date")

        # 상태별 날짜 요구사항 (기존 로직 유지)
        if status in ("active",):
            if not sdate:
                self.add_error("start_date", "진행 상태는 시작일이 필요합니다.")
        if status in ("completed",):
            if not sdate:
                self.add_error("start_date", "완료 상태는 시작일이 필요합니다.")
            if not edate:
                self.add_error("end_date", "완료 상태는 종료일이 필요합니다.")

        # 날짜 논리 검증
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
    # 프로젝트 폼도 동일하게 ISO 위젯을 쓰려면 아래처럼 교체 가능
    start_date = forms.DateField(required=False, input_formats=["%Y-%m-%d", "%Y%m%d"], widget=ISODateInput())
    end_date   = forms.DateField(required=False, input_formats=["%Y-%m-%d", "%Y%m%d"], widget=ISODateInput())

    class Meta:
        model = Project
        fields = [
            "contract", "code", "name",
            "start_date", "end_date",
            "status", "description", "org_unit_id",
        ]
        # widgets = { "start_date": forms.DateInput(attrs={"type": "date"}), "end_date": forms.DateInput(attrs={"type": "date"}) }
        # ↑ 위젯 충돌 방지를 위해 주석 처리/제거
    
class ProjectNoteForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["description"]  # ← 딱 비고만

class MyOrgUnitForm(forms.ModelForm):
    class Meta:
        model = MyOrgUnit
        fields = ["name", "type", "biz_no", "rep_name", "phone", "email",
                  "address", "label", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.TextInput(attrs={"class": "form-control"}),
            "biz_no": forms.TextInput(attrs={"class": "form-control"}),
            "rep_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),  # ⬅ 한 줄
            "label": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

