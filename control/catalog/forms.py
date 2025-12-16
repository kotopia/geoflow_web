# control/catalog/forms.py
from django import forms
from .models import CategoryOptionSet, CategoryOptionRule, CategoryFacet, CategoryFacetOption, CategoryNode

class OptionSetForm(forms.ModelForm):
    class Meta:
        model = CategoryOptionSet
        fields = ['l2', 'facet', 'level_no', 'ord']
    level_no = forms.ChoiceField(choices=[(3, 'Level 3'), (4, 'Level 4')])

    def clean(self):
        c = super().clean()
        # L2는 반드시 level=2
        l2: CategoryNode = c.get('l2')
        if l2 and l2.level != 2:
            raise forms.ValidationError('중분류(L2) 노드만 선택할 수 있습니다.')
        return c

class OptionRuleForm(forms.ModelForm):
    class Meta:
        model = CategoryOptionRule
        fields = ['l2', 'facet3_opt', 'facet4_opt', 'active']

    def __init__(self, *args, **kwargs):
        l2 = kwargs.pop('l2', None)
        super().__init__(*args, **kwargs)
        # 같은 L2에서 선택 가능한 옵션만 보이도록 필터링
        if l2:
            self.fields['l2'].initial = l2
            self.fields['l2'].widget = forms.HiddenInput()
            # L2에 붙은 L3/L4 옵션팩을 찾아 옵션 풀 구성
            sets = CategoryOptionSet.objects.filter(l2=l2)
            facet3 = sets.filter(level_no=3).values_list('facet_id', flat=True)
            facet4 = sets.filter(level_no=4).values_list('facet_id', flat=True)
            self.fields['facet3_opt'].queryset = CategoryFacetOption.objects.filter(facet_id__in=facet3, active=True).order_by('ord','name')
            self.fields['facet4_opt'].queryset = CategoryFacetOption.objects.filter(facet_id__in=facet4, active=True).order_by('ord','name')

class AdminKitFormMixin:
    """AdminKit/Bootstrap5에 맞는 기본 위젯 클래스 부여"""
    input_like = (
        forms.TextInput, forms.NumberInput, forms.EmailInput, forms.URLInput,
        forms.PasswordInput, forms.DateInput, forms.DateTimeInput,
        forms.TimeInput, forms.Textarea
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, self.input_like):
                w.attrs.setdefault('class', 'form-control form-control-sm')
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault('class', 'form-select form-select-sm')
            elif isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault('class', 'form-check-input')
        # 선택: placeholder 기본값
        if 'code' in self.fields:
            self.fields['code'].widget.attrs.setdefault('placeholder', '코드')
        if 'name' in self.fields:
            self.fields['name'].widget.attrs.setdefault('placeholder', '이름')

class L1Form(AdminKitFormMixin, forms.ModelForm):
    class Meta:
        model = CategoryNode
        fields = ['code', 'name', 'ord', 'active']  # 실제 필드명에 맞게
        widgets = {
            'ord': forms.NumberInput(attrs={'min': 1}),
        }

class L2Form(forms.ModelForm):
    class Meta:
        model = CategoryNode
        fields = ['code', 'name', 'ord', 'active']
        
class FacetForm(forms.ModelForm):
    class Meta:
        model = CategoryFacet
        fields = ['code', 'name', 'ord', 'active']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'FACET_PROCESS'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '공정팩'}),
            'ord':  forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

# 1) DB 제약과 동일한 choice 상수 정의
DEFAULT_UNIT_CHOICES = [
    ('EA',  'EA'),
    ('점',  '점'),
    ('식',  '식'),
    ('m',   'm'),
    ('㎡',  '㎡'),
    ('km',  'km'),
    ('㎢',  '㎢'),
    ('NONE','NONE'),
]

GEOM_HINT_CHOICES = [
    ('POINT',   'POINT'),
    ('LINE',    'LINE'),
    ('POLYGON', 'POLYGON'),
    ('NONE',    'NONE'),
]

class FacetOptionForm(forms.ModelForm):
    class Meta:
        model  = CategoryFacetOption
        fields = ['code', 'name', 'ord', 'active', 'default_unit', 'geom_hint']

        # ✅ Select로 변경 (자유 텍스트 금지)
        widgets = {
            'code':   forms.TextInput(attrs={'class': 'form-control', 'maxlength': 20}),
            'name':   forms.TextInput(attrs={'class': 'form-control', 'maxlength': 20}),
            'ord':    forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            # ↓↓↓ 여기 중요
            'default_unit': forms.Select(choices=DEFAULT_UNIT_CHOICES, attrs={'class': 'form-select'}),
            'geom_hint':    forms.Select(choices=GEOM_HINT_CHOICES,    attrs={'class': 'form-select'}),
        }

    # facet은 URL에서 주입(히든)하므로 폼 필드에 노출하지 않습니다.
    def __init__(self, *args, **kwargs):
        self.facet = kwargs.pop('facet', None)
        super().__init__(*args, **kwargs)
        # 초기값이 비어있다면 안전하게 'NONE'으로
        if not self.instance.pk:
            self.fields['default_unit'].initial = 'NONE'
            self.fields['geom_hint'].initial    = 'NONE'

    # 빈 값/소문자 등 들어오면 DB 제약에 맞게 교정
    def clean_default_unit(self):
        val = self.cleaned_data.get('default_unit') or 'NONE'
        return val if val in dict(DEFAULT_UNIT_CHOICES) else 'NONE'

    def clean_geom_hint(self):
        val = self.cleaned_data.get('geom_hint') or 'NONE'
        # 혹시 소문자/소문자 혼입 대비
        val = str(val).upper()
        return val if val in dict(GEOM_HINT_CHOICES) else 'NONE'

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.facet is not None:
            obj.facet = self.facet
        if commit:
            obj.save()
        return obj