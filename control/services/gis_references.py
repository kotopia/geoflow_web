"""Central reference metadata and append-only original-file intake (no tenant DB)."""

import ipaddress
import re
from datetime import date
from urllib.parse import urlsplit
from uuid import UUID, uuid4

KINDS = {
    "map_sheet": "1:1,000 도엽",
    "legal_boundary": "법정동 경계",
    "admin_boundary": "행정동 경계",
    "cadastral": "지적도",
    "cadastral_control": "지적기준점",
    "integrated_control": "통합기준점",
    "local_control": "지역 기준점",
    "other": "기타 참조자료",
}
SOURCE_KINDS = {
    "manual": "수동 업로드",
    "api": "API",
    "file_url": "파일 주소",
    "page": "자료 게시판",
}


class ReferenceError(ValueError):
    pass


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ReferenceError("자료 식별자가 올바르지 않습니다.") from None


def text(payload, key, maximum, required=False):
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ReferenceError("입력값 형식을 확인하세요.")
    value = value.strip()
    if (
        len(value) > maximum
        or (required and not value)
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise ReferenceError("필수 입력값과 최대 길이를 확인하세요.")
    return value


def enabled(payload):
    value = payload.get("enabled", True)
    if not isinstance(value, bool):
        raise ReferenceError("사용 여부는 참/거짓이어야 합니다.")
    return value


def source_url(value):
    if not value:
        return ""
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (
            url.scheme != "https"
            or not host
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError
        if host == "localhost" or host.endswith((".local", ".localhost")):
            raise ValueError
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError
        except ValueError:
            if re.fullmatch(r"[\d.:]+", host) or ":" in host:
                raise ValueError
        if url.port not in (None, 443):
            raise ValueError
    except ValueError:
        raise ReferenceError(
            "공개 HTTPS 기본 주소를 입력하세요. 인증키·쿼리·로그인 정보는 주소에 넣지 마세요."
        ) from None
    return value


def secret_reference(value):
    if not value:
        return ""
    # Only a server-managed reference, never a raw key. Not resolved during registration.
    if not re.fullmatch(
        r"aws-secretsmanager:geoflow/gis/references/[A-Za-z0-9/_+=.@-]{1,180}(?:#[A-Za-z0-9_-]{1,64})?",
        value,
    ):
        raise ReferenceError(
            "API 키 원문 대신 geoflow/gis/references/ 아래의 서버 비밀 참조를 입력하세요."
        )
    return value


def rows(cur):
    names = [c[0] for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def ready(cur):
    cur.execute(
        "SELECT to_regclass('gis.reference_source'), to_regclass('gis.reference_dataset'), "
        "to_regclass('gis.reference_version'), to_regclass('gis.reference_event')"
    )
    return all(cur.fetchone())


def snapshot(cur, history_page=1):
    cur.execute(
        "SELECT id,name,kind,url,(secret_ref <> '') AS credential_configured,enabled,revision "
        "FROM gis.reference_source ORDER BY name,id"
    )
    sources = rows(cur)
    cur.execute(
        "SELECT d.*, (SELECT count(*) FROM gis.reference_version v "
        "WHERE v.dataset_id=d.id AND v.status='stored') AS stored_versions "
        "FROM gis.reference_dataset d ORDER BY d.name,d.id"
    )
    datasets = rows(cur)
    cur.execute("SELECT count(*) FROM gis.reference_event")
    history_count = cur.fetchone()[0]
    cur.execute(
        "SELECT e.id,e.action,e.created_at,d.name AS dataset_name,s.name AS source_name,"
        "v.label AS version_label,v.status AS version_status "
        "FROM gis.reference_event e LEFT JOIN gis.reference_dataset d ON d.id=e.dataset_id "
        "LEFT JOIN gis.reference_source s ON s.id=e.source_id "
        "LEFT JOIN gis.reference_version v ON v.id=e.version_id "
        "ORDER BY e.created_at DESC,e.id DESC LIMIT 50 OFFSET %s",
        [(history_page - 1) * 50],
    )
    return {
        "sources": sources,
        "datasets": datasets,
        "events": rows(cur),
        "history_count": history_count,
        "history_page": history_page,
        "kinds": KINDS,
        "source_kinds": SOURCE_KINDS,
    }


def versions(cur, dataset_id):
    dataset_id = identifier(dataset_id)
    cur.execute(
        "SELECT id,label,published_on,declared_crs,filename,size_bytes,sha256,status,error_code,created_at "
        "FROM gis.reference_version WHERE dataset_id=%s ORDER BY created_at DESC,id",
        [dataset_id],
    )
    return rows(cur)


def event(cur, actor, action, dataset_id=None, source_id=None, version_id=None):
    cur.execute(
        "INSERT INTO gis.reference_event(id,actor_id,action,dataset_id,source_id,version_id) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        [str(uuid4()), identifier(actor), action, dataset_id, source_id, version_id],
    )


def mutate(cur, payload, actor):
    if not isinstance(payload, dict):
        raise ReferenceError("요청은 객체여야 합니다.")
    action = payload.get("action")
    if action not in ("save_source", "save_dataset"):
        raise ReferenceError("지원하지 않는 작업입니다.")
    kind = payload.get("kind")
    is_source = action == "save_source"
    if not isinstance(kind, str) or kind not in (SOURCE_KINDS if is_source else KINDS):
        raise ReferenceError("자료 또는 연결 종류를 선택하세요.")
    item_id = identifier(payload["id"]) if payload.get("id") else str(uuid4())
    table = "gis.reference_source" if is_source else "gis.reference_dataset"
    old = None
    if payload.get("id"):
        cur.execute(f"SELECT revision FROM {table} WHERE id=%s FOR UPDATE", [item_id])
        old = cur.fetchone()
        if (
            not old
            or type(payload.get("revision")) is not int
            or payload["revision"] != old[0]
        ):
            raise ReferenceError("다른 변경이 있습니다. 새로고침 후 다시 저장하세요.")
    values = {
        "name": text(payload, "name", 160, True),
        "kind": kind,
        "enabled": enabled(payload),
    }
    if is_source:
        values["url"] = source_url(text(payload, "url", 1000))
        if kind != "manual" and not values["url"]:
            raise ReferenceError("API 또는 자료 주소를 입력하세요.")
        if kind == "manual" and values["url"]:
            raise ReferenceError("수동 업로드에는 연결 주소가 필요하지 않습니다.")
        if "secret_ref" in payload:
            values["secret_ref"] = secret_reference(text(payload, "secret_ref", 300))
            if kind != "api" and values["secret_ref"]:
                raise ReferenceError("API 연결에만 비밀 참조를 지정할 수 있습니다.")
        if kind != "api":
            values["secret_ref"] = ""
    else:
        code = text(payload, "code", 64, True)
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", code):
            raise ReferenceError(
                "자료 코드는 영문 소문자로 시작하는 영문·숫자·밑줄 2~64자입니다."
            )
        if old:
            cur.execute("SELECT code FROM gis.reference_dataset WHERE id=%s", [item_id])
            if cur.fetchone()[0] != code:
                raise ReferenceError("등록된 자료 코드는 변경할 수 없습니다.")
        values.update(
            code=code,
            region=text(payload, "region", 160),
            publisher=text(payload, "publisher", 160),
            description=text(payload, "description", 2000),
            usage_terms=text(payload, "usage_terms", 2000),
        )
        values["source_id"] = (
            identifier(payload["source_id"]) if payload.get("source_id") else None
        )
        if values["source_id"]:
            cur.execute(
                "SELECT id FROM gis.reference_source WHERE id=%s", [values["source_id"]]
            )
            if not cur.fetchone():
                raise ReferenceError("연결을 찾을 수 없습니다.")
    columns = list(values)
    if old:
        cur.execute(
            f"UPDATE {table} SET "
            + ",".join(f"{c}=%s" for c in columns)
            + ",revision=revision+1,updated_at=now() WHERE id=%s",
            [*values.values(), item_id],
        )
    else:
        cur.execute(
            f"INSERT INTO {table}(id,"
            + ",".join(columns)
            + ") VALUES ("
            + ",".join(["%s"] * (len(columns) + 1))
            + ")",
            [item_id, *values.values()],
        )
    event(
        cur,
        actor,
        ("source" if is_source else "dataset") + ("_updated" if old else "_created"),
        source_id=item_id if is_source else None,
        dataset_id=None if is_source else item_id,
    )
    return item_id


def reserve_version(cur, actor, dataset_id, payload, info):
    dataset_id = identifier(dataset_id)
    cur.execute(
        "SELECT enabled FROM gis.reference_dataset WHERE id=%s FOR UPDATE", [dataset_id]
    )
    found = cur.fetchone()
    if not found or not found[0]:
        raise ReferenceError("활성 자료에만 원본을 추가할 수 있습니다.")
    label = text(payload, "label", 120, True)
    crs = text(payload, "declared_crs", 40)
    if crs and not re.fullmatch(r"EPSG:[1-9][0-9]{2,6}", crs):
        raise ReferenceError(
            "좌표계는 EPSG:5186 형식으로 입력하세요. 모르면 비워 두세요."
        )
    try:
        published = (
            date.fromisoformat(text(payload, "published_on", 10))
            if payload.get("published_on")
            else None
        )
    except ValueError:
        raise ReferenceError("자료 기준일을 확인하세요.") from None
    version_id = str(uuid4())
    key = f"central/gis/references/{dataset_id}/{version_id}/original{info['suffix']}"
    cur.execute(
        "INSERT INTO gis.reference_version(id,dataset_id,label,published_on,declared_crs,filename,"
        "size_bytes,sha256,object_key,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
        [
            version_id,
            dataset_id,
            label,
            published,
            crs,
            info["filename"],
            info["size"],
            info["sha256"],
            key,
        ],
    )
    event(cur, actor, "upload_started", dataset_id=dataset_id, version_id=version_id)
    return version_id, key


def finish_version(cur, actor, version_id, success):
    cur.execute(
        "UPDATE gis.reference_version SET status=%s,error_code=%s,updated_at=now() "
        "WHERE id=%s AND status='pending' RETURNING dataset_id",
        [
            "stored" if success else "failed",
            "" if success else "storage_failed",
            identifier(version_id),
        ],
    )
    found = cur.fetchone()
    if not found:
        raise ReferenceError("이미 처리된 원본입니다.")
    event(
        cur,
        actor,
        "upload_stored" if success else "upload_failed",
        dataset_id=found[0],
        version_id=version_id,
    )
