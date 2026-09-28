"""Pure selection rules shared by QGIS now and QField contract later."""


def resolve_selection(policy, template_id="", variant_id="", template_variants=None):
    templates = list((policy or {}).get("templates") or [])
    if not templates:
        return "", ""
    template = next((row for row in templates if str(row.get("id")) == str(template_id)), None)
    template = template or templates[0]
    variants = list(template.get("variants") or [])
    if not variants:
        return str(template.get("id") or ""), ""
    remembered = str((template_variants or {}).get(str(template.get("id") or "")) or "")
    wanted = str(variant_id or remembered)
    variant = next((row for row in variants if str(row.get("id")) == wanted), None) or variants[0]
    return str(template.get("id") or ""), str(variant.get("id") or "")
