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


def next_photo_slot(variant, photos, last_slot_id=""):
    """Return the next useful slot without making every feature photo-required."""
    slots = list((variant or {}).get("slots") or [])
    effective = [row for row in (photos or []) if not row.get("_pending_delete")]

    def count(slot):
        slot_id = str(slot.get("id") or "")
        return sum(str(row.get("slot_id") or "") == slot_id for row in effective)

    for slot in slots:
        if count(slot) < int(slot.get("min_count") or 0):
            return slot
    remembered = next(
        (slot for slot in slots if str(slot.get("id") or "") == str(last_slot_id)), None
    )
    if remembered is not None and count(remembered) < int(remembered.get("max_count") or 100):
        return remembered
    return next(
        (slot for slot in slots if count(slot) < int(slot.get("max_count") or 100)), None
    )


def photo_classification_options(policy, include_extra=True):
    """Flatten ordered catalogue choices for pending-photo reclassification."""
    result = []
    for template in (policy or {}).get("templates") or []:
        for variant in template.get("variants") or []:
            for slot in variant.get("slots") or []:
                result.append({
                    "template_id": str(template.get("id") or ""),
                    "variant_id": str(variant.get("id") or ""),
                    "slot_id": str(slot.get("id") or ""),
                    "label": " / ".join(str(value) for value in (
                        template.get("name") or "사진",
                        variant.get("name") or "기본",
                        slot.get("name") or "사진",
                    )),
                })
    if include_extra:
        result.append({"template_id": "", "variant_id": "", "slot_id": "",
                       "label": "추가 사진"})
    return result
