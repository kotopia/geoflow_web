from datetime import date
from django import forms
from django.utils import timezone
from .company_models import CompanyProfile, CompanyRegistration, CompanyRevenue, CompanyHeadcount, CompanyCredit


class FactForm(forms.ModelForm):
    def __init__(self, *args, alias=None, **kwargs):
        super().__init__(*args, **kwargs)
        if alias:
            from .services.company_references import apply_references
            apply_references(self, alias)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-check-input' if isinstance(field.widget, forms.CheckboxInput) else 'form-control'
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(format='%Y-%m-%d', attrs={'type':'date','class':'form-control'})
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs['rows'] = 3

    def clean(self):
        data = super().clean()
        start = data.get('occurred_on') or data.get('evaluated_on')
        if start and data.get('expires_on') and data['expires_on'] < start:
            self.add_error('expires_on', '만료일은 등록·평가일 이후여야 합니다.')
        return data


class ProfileForm(FactForm):
    def _get_validation_exclusions(self):
        # Representative/default selection is serialized in the tenant transaction.
        return super()._get_validation_exclusions() | {'is_primary'}

    class Meta:
        model = CompanyProfile
        fields = ['node_kind','is_primary','industry','business','founded_on','legal_form','enterprise_size','homepage','capital','corporate_no','fax']
        labels = {'node_kind':'사업장 구분','is_primary':'기본 기업으로 지정'}


class RegistrationForm(FactForm):
    class Meta:
        model = CompanyRegistration
        fields = ['kind','name','number','occurred_on','issued_on','issuer','status','valid_from','expires_on','items','memo']
        widgets = {'items': forms.HiddenInput()}
        labels = {'occurred_on':'최초 등록·신고·발급일'}

    def clean_items(self):
        items = self.cleaned_data.get('items') or []
        if not isinstance(items, list) or len(items) > 50:
            raise forms.ValidationError('대상 품목은 최대 50개까지 입력할 수 있습니다.')
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                raise forms.ValidationError('품목 형식을 확인하세요.')
            row = {key: str(item.get(key) or '').strip() for key in ('code','name','valid_from','expires_on')}
            if not row['name'] or len(row['name']) > 200 or len(row['code']) > 100:
                raise forms.ValidationError('각 품목의 명칭과 코드를 확인하세요.')
            try:
                start = date.fromisoformat(row['valid_from']) if row['valid_from'] else None
                end = date.fromisoformat(row['expires_on']) if row['expires_on'] else None
            except ValueError:
                raise forms.ValidationError('품목 유효기간을 확인하세요.')
            if start and end and end < start:
                raise forms.ValidationError('품목 종료일은 시작일 이후여야 합니다.')
            cleaned.append(row)
        return cleaned

    def clean(self):
        data = super().clean()
        if data.get('valid_from') and data.get('expires_on') and data['expires_on'] < data['valid_from']:
            self.add_error('expires_on', '종료일은 시작일 이후여야 합니다.')
        if data.get('issued_on') and data.get('occurred_on') and data['issued_on'] < data['occurred_on']:
            self.add_error('issued_on', '발급일은 최초 등록·신고일 이후여야 합니다.')
        return data


class RevenueForm(FactForm):
    class Meta:
        model = CompanyRevenue
        fields = ['year','fiscal_on','amount','confirmed','source']
    def clean(self):
        data = super().clean()
        if data.get('year') and data.get('fiscal_on') and data['fiscal_on'].year != data['year']:
            self.add_error('fiscal_on', '결산 기준일의 연도와 회계연도가 일치해야 합니다.')
        return data


class HeadcountForm(FactForm):
    class Meta:
        model = CompanyHeadcount
        fields = ['year','count','source']
    def clean_year(self):
        year = self.cleaned_data['year']
        if year >= timezone.localdate().year:
            raise forms.ValidationError('과거 연말 인원만 입력합니다. 현재 인원은 HR에서 집계합니다.')
        return year


class CreditForm(FactForm):
    class Meta:
        model = CompanyCredit
        fields = ['agency','rating_type','grade','evaluated_on','expires_on','fiscal_on','representative']


class CompanyEventForm(forms.Form):
    title = forms.CharField(label='이벤트명', max_length=255, widget=forms.TextInput(attrs={'class':'form-control'}))
    occurred_at = forms.DateField(label='발생일', widget=forms.DateInput(attrs={'type':'date','class':'form-control'}))
    memo = forms.CharField(label='내용', required=False, widget=forms.Textarea(attrs={'class':'form-control','rows':3}))
