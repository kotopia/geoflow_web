from django import forms
from django.utils import timezone
from .company_models import CompanyProfile, CompanyRegistration, CompanyRevenue, CompanyHeadcount, CompanyCredit


class FactForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
        labels = {'node_kind':'기업/지점 구분','is_primary':'기본 기업으로 지정'}


class RegistrationForm(FactForm):
    class Meta:
        model = CompanyRegistration
        fields = ['kind','name','number','occurred_on','issuer','status','expires_on','memo']


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
