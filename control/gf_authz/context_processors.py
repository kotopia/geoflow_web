from .permissions import gf_has_perm, gf_has_role

def gf_authz(request):
    # 템플릿에서: {% if gf_has_perm 'maps.view' %} ... {% endif %}
    return {
        "gf_has_perm": lambda code: gf_has_perm(request, code),
        "gf_has_role": lambda code: gf_has_role(request, code),
    }
