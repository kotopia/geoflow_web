"""Company selectors use the existing tenant settings tree; stored text is a historical snapshot."""
from django import forms
from django.db import connections

REFERENCES = {
    'legal_form': ('company.legal_form', '기업형태'),
    'enterprise_size': ('company.enterprise_size', '기업규모'),
    'agency': ('company.credit_agency', '평가기관'),
    'rating_type': ('company.rating_type', '평가종류'),
    'name': ('company.document_name', '증명·평가 명칭'),
}


def reference_groups(alias):
    with connections[alias].cursor() as cursor:
        cursor.execute('''SELECT category.field_ref, child.name, child.active, child.ord
            FROM ops.settings_nodes category
            LEFT JOIN ops.settings_nodes child ON child.parent_id=category.id AND child.node_type='value'
            WHERE category.field_ref = ANY(%s) AND category.active=true
            ORDER BY child.ord, child.name, child.id''', [[value[0] for value in REFERENCES.values()]])
        rows = cursor.fetchall()
    return [{'field':field, 'label':label, 'ref':ref,
             'options':[{'name':name, 'active':active} for key,name,active,_ in rows if key==ref and name]}
            for field,(ref,label) in REFERENCES.items()]


def apply_references(form, alias):
    form.reference_suggestions = []
    for group in reference_groups(alias):
        key = group['field']
        if key not in form.fields:
            continue
        field = form.fields[key]
        names = list(dict.fromkeys(o['name'] for o in group['options'] if o['active']))
        current = str(getattr(form.instance, key, '') or '')
        if current and current not in names:
            names.append(current)  # Preserve existing/inactive historical values on this record only.
        if key in {'legal_form','enterprise_size'}:
            form.fields[key] = forms.ChoiceField(label=field.label, required=False,
                choices=[('', '선택하세요')] + [(name,name) for name in names])
            form.fields[key].help_text = '기준값 관리에서 선택 항목을 관리합니다.'
        else:
            # Document/agency names remain open input; a new issuer must not be blocked by a UI catalogue.
            field.widget.attrs['list'] = 'company-options-' + key
            group['names'] = names
            form.reference_suggestions.append(group)
