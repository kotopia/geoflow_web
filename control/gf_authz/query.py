def gf_scope_queryset(qs, request, project_field="project_id", tenant_field="tenant_id"):
    if tenant_field and getattr(request, "gf_tenant_id", None) is not None:
        qs = qs.filter(**{tenant_field: request.gf_tenant_id})
    proj_ids = getattr(request, "gf_project_ids", None)
    if proj_ids:
        qs = qs.filter(**{f"{project_field}__in": list(proj_ids)})
    return qs
