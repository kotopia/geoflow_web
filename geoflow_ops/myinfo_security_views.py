from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from control.gf_authz.permissions import gf_has_perm

from . import views_myinfo
from .services.entity_access import require_tenant_context


def _require_directory_edit(request):
    require_tenant_context(request)
    if not gf_has_perm(request, "directory.edit"):
        raise PermissionDenied("Permission denied")


@never_cache
@login_required
@require_POST
def orgunit_department_save(request, pk):
    _require_directory_edit(request)
    return views_myinfo.orgunit_department_save(request, pk)


@never_cache
@login_required
@require_POST
def job_grade_save(request, pk):
    _require_directory_edit(request)
    return views_myinfo.job_grade_save(request, pk)


@never_cache
@login_required
@require_POST
def job_position_save(request, pk):
    _require_directory_edit(request)
    return views_myinfo.job_position_save(request, pk)
