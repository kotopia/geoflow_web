from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from geoflow_ops.models import Contract, Project

PROJECT_MODES = (("SINGLE", "단일 프로젝트"), ("MULTIPLE", "복수 프로젝트"))
PROJECT_FIELDS = ("name", "start_date", "end_date", "status", "description")
CONTRACT_FIELDS = ("code", "name", "start_date", "end_date", "amount", "kind", "division",
                   "client_id", "sub_client_id", "org_unit_id", "description")


def policy_ext(contract):
    if contract.ext is not None and not isinstance(contract.ext, dict):
        raise ValidationError("계약의 확장정보를 확인해야 합니다.")
    return dict(contract.ext or {})


def project_mode(contract):
    mode = policy_ext(contract).get("project_mode")
    if mode not in dict(PROJECT_MODES):
        raise ValidationError("계약의 프로젝트 운영방식을 먼저 설정하세요.")
    return mode


def normalized_name(name):
    return " ".join(unicodedata.normalize("NFKC", str(name or "")).split()).casefold()


def _next_code(alias, contract):
    ext = policy_ext(contract)
    last = ext.get("project_sequence", 0)
    if type(last) is not int or last < 0:
        raise ValidationError("프로젝트 순번 설정을 확인해야 합니다.")
    prefix = str(contract.code or "").strip()
    if not prefix:
        raise ValidationError("계약번호를 먼저 입력하세요.")
    # Also inspect existing rows when the counter has not yet been initialized.
    for code in Project.objects.using(alias).filter(contract_id=contract.pk).values_list("code", flat=True):
        match = re.fullmatch(re.escape(prefix) + r"-(\d{3,})", str(code or ""))
        if match:
            last = max(last, int(match[1]))
    last += 1
    code = f"{prefix}-{last:03d}"
    if Project.objects.using(alias).filter(code=code).exists():
        raise ValidationError("생성할 프로젝트코드가 이미 사용 중입니다. 계약번호를 확인하세요.")
    ext["project_sequence"] = last
    contract.ext = ext
    contract.save(using=alias, update_fields=["ext"])
    return code


def _create_locked(alias, contract, values, *, allow_duplicate=False, now=None):
    mode = project_mode(contract)
    projects = Project.objects.using(alias).filter(contract_id=contract.pk)
    if mode == "SINGLE" and projects.exists():
        raise ValidationError("단일 프로젝트 계약에는 프로젝트를 추가할 수 없습니다.")
    values = {key: values.get(key) for key in PROJECT_FIELDS}
    if mode == "SINGLE":
        values["name"] = contract.name
    elif not normalized_name(values["name"]):
        raise ValidationError("프로젝트명을 입력하세요.")
    elif not allow_duplicate and any(normalized_name(n) == normalized_name(values["name"])
                                    for n in projects.values_list("name", flat=True)):
        raise ValidationError("같은 계약에 동일한 프로젝트명이 있습니다. 중복 이름 확인을 선택하세요.", code="duplicate_name")
    stamp = now or timezone.now()
    return Project.objects.using(alias).create(
        contract_id=contract.pk, code=_next_code(alias, contract), **values,
        org_unit_id=contract.org_unit_id, ext={}, created_at=stamp, updated_at=stamp,
    )


def create_project(alias, contract_id, values, *, allow_duplicate=False, now=None):
    if not alias or alias == "default":
        raise ValueError("tenant database alias is required")
    with transaction.atomic(using=alias):
        contract = Contract.objects.using(alias).select_for_update().get(pk=contract_id)
        return _create_locked(alias, contract, values, allow_duplicate=allow_duplicate, now=now)


def create_project_for_new_contract(alias: str, contract: Contract, *, now=None):
    """Caller owns the contract+project transaction; MULTIPLE creates no child."""
    if project_mode(contract) == "MULTIPLE":
        return None
    return create_project(alias, contract.pk, {
        "name": contract.name, "start_date": contract.start_date,
        "end_date": contract.end_date, "status": "active", "description": None,
    }, now=now)


def save_contract(alias, instance, mode, *, confirm_single=False):
    if mode not in dict(PROJECT_MODES):
        raise ValidationError("프로젝트 운영방식이 올바르지 않습니다.")
    with transaction.atomic(using=alias):
        locked = Contract.objects.using(alias).select_for_update().get(pk=instance.pk)
        ext = policy_ext(locked)
        previous_mode = ext.get("project_mode")
        projects = Project.objects.using(alias).filter(contract_id=locked.pk)
        if mode == "SINGLE":
            if projects.count() > 1:
                raise ValidationError("프로젝트가 2개 이상이면 단일 방식으로 변경할 수 없습니다.")
            if previous_mode == "MULTIPLE" and projects.exists() and not confirm_single:
                raise ValidationError("단일 방식 전환 시 프로젝트명이 계약명으로 바뀝니다. 확인을 선택하세요.")
        for field in CONTRACT_FIELDS:
            setattr(locked, field, getattr(instance, field))
        ext["project_mode"] = mode
        locked.ext = ext
        locked.updated_at = timezone.now()
        locked.save(using=alias, update_fields=[*CONTRACT_FIELDS, "ext", "updated_at"])
        if mode == "SINGLE":
            projects.exclude(name=locked.name).update(name=locked.name, updated_at=locked.updated_at)
        return locked


def save_project(alias, project_id, values, *, allow_duplicate=False):
    # Lock order always Contract then Project, shared with mode/name changes.
    contract_id = Project.objects.using(alias).values_list("contract_id", flat=True).get(pk=project_id)
    if not contract_id:
        raise ValidationError("연결 계약을 확인해야 합니다.")
    with transaction.atomic(using=alias):
        contract = Contract.objects.using(alias).select_for_update().get(pk=contract_id)
        project = Project.objects.using(alias).select_for_update().get(pk=project_id, contract_id=contract_id)
        mode = project_mode(contract)
        name = values.get("name")
        if mode == "SINGLE":
            if name != contract.name:
                raise ValidationError("단일 프로젝트명은 계약명을 따릅니다. 새로고침 후 저장하세요.")
        elif not normalized_name(name):
            raise ValidationError("프로젝트명을 입력하세요.")
        elif not allow_duplicate:
            others = Project.objects.using(alias).filter(contract_id=contract_id).exclude(pk=project_id)
            if any(normalized_name(n) == normalized_name(name) for n in others.values_list("name", flat=True)):
                raise ValidationError("같은 계약에 동일한 프로젝트명이 있습니다. 중복 이름 확인을 선택하세요.", code="duplicate_name")
        for field in PROJECT_FIELDS:
            setattr(project, field, values.get(field))
        project.updated_at = timezone.now()
        project.save(using=alias, update_fields=[*PROJECT_FIELDS, "updated_at"])
        return project


def contract_id_from_create_response(response) -> UUID:
    if not (300 <= int(getattr(response, "status_code", 0)) < 400):
        raise ValueError("contract create response is not a redirect")
    path = str(getattr(response, "url", "") or "").split("?", 1)[0].rstrip("/")
    try:
        return UUID(path.rsplit("/", 1)[-1])
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError("contract create redirect did not contain a UUID") from exc
