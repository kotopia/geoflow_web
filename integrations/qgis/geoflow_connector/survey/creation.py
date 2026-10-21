"""Copy ordinary Survey attributes once when creating a GIS object."""

def apply_target_inheritance(feature, layer, point, *, project_id=""):
    """Copy Survey attributes to any generated facility through one field map.

    ``QgsVectorLayerUtils.createFeature`` has already applied provider defaults.
    Non-empty Survey values deliberately override those defaults; missing Survey
    values leave the target policy untouched.
    """
    names = {str(name).casefold(): str(name) for name in layer.fields().names()}
    applied = {}

    def assign(candidates, value, *, allow_null=False):
        if value in (None, "") and not allow_null:
            return
        for candidate in candidates:
            physical = names.get(candidate.casefold())
            if physical is not None:
                feature.setAttribute(layer.fields().indexFromName(physical), value)
                applied[physical] = value
                return

    assign(("project_id",), project_id)
    assign(("worker_id",), point.get("worker_id"))
    # Never inherit a provider/UI sentinel such as 1900-01-01 when the Survey
    # did not supply a date. The authoritative missing value is NULL.
    assign(("date", "survey_date"), point.get("survey_date"), allow_null=True)
    assign(("survey_no",), point.get("survey_no"))
    return applied
