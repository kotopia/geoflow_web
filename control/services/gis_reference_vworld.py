"""VWorld credentials and bounded requests to fixed official endpoints only."""

import json
import os
import re
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from control.services import gis_references as refs
from control.services.gis_references import ReferenceError, identifier

SECRET_ID = "geoflow/gis/references/vworld"
ENDPOINT = "https://api.vworld.kr/req/data"
SERVICES = {
    "parcel": {"label": "지번·PNU", "data": "LP_PA_CBND_BUBUN", "kind": "cadastral"},
    "legal_dong": {
        "label": "법정동",
        "data": "LT_C_ADEMD_INFO",
        "kind": "legal_boundary",
    },
    "legal_ri": {"label": "법정리", "data": "LT_C_ADRI_INFO", "kind": "legal_boundary"},
}
MAX_RESPONSE = 8 * 1024 * 1024


def credential_ready(cur):
    cur.execute("SELECT to_regclass('gis.reference_provider_credential')")
    return bool(cur.fetchone()[0])


def credential_status(cur):
    if not credential_ready(cur):
        return {"ready": False, "configured": False, "revision": 0, "domain": ""}
    cur.execute(
        "SELECT domain,revision FROM gis.reference_provider_credential WHERE provider='vworld'"
    )
    row = cur.fetchone()
    return {
        "ready": True,
        "configured": bool(row or getattr(settings, "VWORLD_API_KEY", "")),
        "mode": "registered" if row else "runtime",
        "revision": row[1] if row else 0,
        "domain": row[0]
        if row
        else os.environ.get("GEOFLOW_VWORLD_DOMAIN", "https://geoflow.co.kr"),
    }


def secret_client():
    return boto3.client(
        "secretsmanager",
        region_name=os.environ.get("AWS_REGION", "ap-northeast-2"),
        config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 0}),
    )


def validate_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{16,128}", value):
        raise ReferenceError("브이월드에서 발급받은 API 키 형식을 확인하세요.")
    return value


def validate_domain(value):
    if not isinstance(value, str) or len(value) > 300:
        raise ReferenceError("브이월드에 등록한 서비스 도메인을 입력하세요.")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or parsed.port not in (None, 443)
        ):
            raise ValueError
    except ValueError:
        raise ReferenceError(
            "서비스 도메인은 https://geoflow.co.kr 형식으로 입력하세요."
        ) from None
    return value.rstrip("/")


@sensitive_variables()
def save_credential(cur, payload, actor, client=None):
    actor = identifier(actor)
    if not credential_ready(cur):
        raise ReferenceError("브이월드 키 저장 구조 적용 전입니다.")
    key = validate_key(payload.get("api_key"))
    domain = validate_domain(payload.get("domain"))
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtext('geoflow.reference.credential.vworld'))"
    )
    cur.execute(
        "SELECT revision FROM gis.reference_provider_credential WHERE provider='vworld' FOR UPDATE"
    )
    current = cur.fetchone()
    revision = current[0] if current else 0
    if type(payload.get("revision")) is not int or payload["revision"] != revision:
        raise ReferenceError("키 설정이 변경되었습니다. 새로고침 후 다시 저장하세요.")
    token = str(uuid4())
    try:
        client = client or secret_client()
        # Fixed dedicated secret only. No tenant credentials, arbitrary paths or IAM writes.
        try:
            response = client.create_secret(
                Name=SECRET_ID,
                ClientRequestToken=token,
                SecretString=json.dumps({"api_key": key}),
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceExistsException":
                raise
            response = client.put_secret_value(
                SecretId=SECRET_ID,
                ClientRequestToken=token,
                SecretString=json.dumps({"api_key": key}),
            )
        version = response.get("VersionId")
        if version != token:
            raise ReferenceError("인증키 저장 결과를 확인하지 못했습니다.")
    except (BotoCoreError, ClientError):
        raise ReferenceError(
            "키를 저장하지 못했습니다. 서버의 브이월드 전용 비밀 저장 권한을 확인하세요."
        ) from None
    cur.execute(
        "INSERT INTO gis.reference_provider_credential(provider,secret_version,domain,revision,actor_id) "
        "VALUES ('vworld',%s,%s,%s,%s) ON CONFLICT(provider) DO UPDATE SET "
        "secret_version=EXCLUDED.secret_version,domain=EXCLUDED.domain,revision=EXCLUDED.revision,"
        "actor_id=EXCLUDED.actor_id,updated_at=now()",
        [version, domain, revision + 1, actor],
    )
    refs.event(cur, actor, "credential_updated")
    # The DB pins the AWS version. A DB rollback keeps the previous working key.
    return {"configured": True, "revision": revision + 1, "domain": domain}


def setup(cur, actor):
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtext('geoflow.reference.setup.vworld'))"
    )
    cur.execute(
        "SELECT id FROM gis.reference_source WHERE kind='api' AND url=%s AND enabled=true ORDER BY created_at,id LIMIT 1",
        [ENDPOINT],
    )
    found = cur.fetchone()
    source = (
        str(found[0])
        if found
        else refs.mutate(
            cur,
            {
                "action": "save_source",
                "name": "브이월드 공통 연결",
                "kind": "api",
                "url": ENDPOINT,
            },
            actor,
        )
    )
    for code, label, kind in (
        ("vworld_parcel", "브이월드 지번·PNU", "cadastral"),
        ("vworld_legal_boundary", "브이월드 법정동·법정리", "legal_boundary"),
    ):
        cur.execute(
            "SELECT source_id,kind FROM gis.reference_dataset WHERE code=%s", [code]
        )
        old = cur.fetchone()
        if old:
            if str(old[0]) != source or old[1] != kind:
                raise ReferenceError(
                    "기존 브이월드 자료 코드의 연결이 다릅니다. 자료 설정을 확인하세요."
                )
            continue
        refs.mutate(
            cur,
            {
                "action": "save_dataset",
                "name": label,
                "code": code,
                "kind": kind,
                "source_id": source,
                "publisher": "브이월드",
            },
            actor,
        )
    return source


@lru_cache(maxsize=4)
@sensitive_variables()
def _version_key(version):
    # Process memory only, never Django's potentially shared/persistent cache backend.
    response = secret_client().get_secret_value(SecretId=SECRET_ID, VersionId=version)
    return validate_key(json.loads(response["SecretString"]).get("api_key"))


@sensitive_variables()
def credential(cur, client=None):
    if not credential_ready(cur):
        raise ReferenceError("브이월드 조회 구조 적용 전입니다.")
    cur.execute(
        "SELECT secret_version,domain FROM gis.reference_provider_credential WHERE provider='vworld'"
    )
    row = cur.fetchone()
    if row is None:
        return validate_key(getattr(settings, "VWORLD_API_KEY", "")), validate_domain(
            os.environ.get("GEOFLOW_VWORLD_DOMAIN", "https://geoflow.co.kr")
        )
    try:
        if client is None:
            return _version_key(row[0]), validate_domain(row[1])
        response = (client or secret_client()).get_secret_value(
            SecretId=SECRET_ID, VersionId=row[0]
        )
        value = json.loads(response["SecretString"])
        return validate_key(value.get("api_key")), validate_domain(row[1])
    except (BotoCoreError, ClientError, ValueError, TypeError, KeyError):
        raise ReferenceError(
            "등록된 브이월드 키를 읽지 못했습니다. 서버 비밀 조회 권한을 확인하세요."
        ) from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@sensitive_variables()
def read_response(url, limit=MAX_RESPONSE, domain=None):
    try:
        headers = {"Accept": "application/json,image/png,image/jpeg"}
        if domain:
            headers["Referer"] = validate_domain(domain) + "/"
        with build_opener(NoRedirect()).open(
            Request(url, headers=headers),
            timeout=8,
        ) as response:
            value = response.read(limit + 1)
            if len(value) > limit:
                raise ReferenceError("조회 결과가 너무 큽니다. 작업 영역을 줄이세요.")
            return value
    except (HTTPError, URLError, OSError, TimeoutError):
        # Never return/log an exception containing the credential-bearing URL.
        raise ReferenceError(
            "브이월드 요청에 실패했습니다. 인증키·도메인·호출한도를 확인하세요."
        ) from None


@sensitive_variables()
def features(service, geometry, key, domain, reader=read_response):
    if service not in SERVICES:
        raise ReferenceError("조회할 브이월드 자료를 선택하세요.")
    # bbox query is followed by exact GEOS intersection in the shared lookup engine.
    xmin, ymin, xmax, ymax = geometry.extent
    params = {
        "service": "data",
        "version": "2.0",
        "request": "GetFeature",
        "format": "json",
        "data": SERVICES[service]["data"],
        "key": key,
        "domain": domain,
        "crs": "EPSG:4326",
        "geomFilter": f"BOX({xmin},{ymin},{xmax},{ymax})",
        "geometry": "true",
        "attribute": "true",
        "size": 100,
        "page": 1,
    }
    if geometry.geom_type == "Point":
        params["geomFilter"] = geometry.wkt
    try:
        response = json.loads(
            reader(ENDPOINT + "?" + urlencode(params), domain=domain)
        )["response"]
        if response.get("status") == "NOT_FOUND":
            return []
        if response.get("status") != "OK":
            raise ReferenceError(
                "브이월드에서 조회를 거절했습니다. 인증키·도메인·호출한도를 확인하세요."
            )
        total = int(response["record"]["total"])
        found = response["result"]["featureCollection"]["features"]
        if total > 100 or len(found) != total:
            raise ReferenceError(
                "조회 후보가 100개를 넘거나 결과가 불완전합니다. 작업 영역을 줄이세요."
            )
        if not isinstance(found, list):
            raise TypeError
        for feature in found:
            if feature.get("id") is None:
                properties = feature.get("properties", {})
                stable = next(
                    (
                        properties.get(field)
                        for field in ("pnu", "emd_cd", "li_cd")
                        if properties.get(field) is not None
                    ),
                    None,
                )
                if stable is None:
                    raise ValueError
                feature["id"] = str(stable)
        return found
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ReferenceError("브이월드 응답 형식을 확인하지 못했습니다.") from None


def tile(style, z, y, x, key, domain, reader=read_response):
    if (
        style not in {"Base", "Satellite", "Hybrid"}
        or not 0 <= z <= 19
        or not (0 <= x < 2**z and 0 <= y < 2**z)
    ):
        raise ReferenceError("지도 타일 범위가 올바르지 않습니다.")
    ext = "jpeg" if style == "Satellite" else "png"
    value = reader(
        f"https://api.vworld.kr/req/wmts/1.0.0/{key}/{style}/{z}/{y}/{x}.{ext}",
        limit=2 * 1024 * 1024,
        domain=domain,
    )
    if not value.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
        raise ReferenceError("브이월드 지도 타일을 받지 못했습니다.")
    return value, "image/jpeg" if ext == "jpeg" else "image/png"
