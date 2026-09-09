from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote, urlparse
from urllib.request import Request, urlopen

from django.conf import settings


NOTICE_OPERATION = "getBidPblancListInfoServc"
LICENSE_OPERATION = "getBidPblancListInfoLicenseLimit"
REGION_OPERATION = "getBidPblancListInfoPrtcptPsblRgn"
BASIS_AMOUNT_OPERATION = "getBidPblancListInfoServcBsisAmount"


class G2BError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code or "G2B_ERROR")[:100]


@dataclass(frozen=True)
class G2BPage:
    items: list[dict[str, Any]]
    total_count: int
    page_no: int
    rows: int


def _items(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        nested = value.get("item")
        if isinstance(nested, list):
            return [row for row in nested if isinstance(row, dict)]
        if isinstance(nested, dict):
            return [nested]
        return [value] if any(key in value for key in ("bidNtceNo", "bidNtceNm")) else []
    return []


def parse_response(payload: dict[str, Any], *, page_no: int, rows: int) -> G2BPage:
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        raise G2BError("INVALID_RESPONSE", "나라장터 API 응답 형식이 올바르지 않습니다.")
    header = response.get("header") or {}
    code = str(header.get("resultCode") or "")
    if code not in {"00", "000"}:
        raise G2BError(code or "API_ERROR", str(header.get("resultMsg") or "나라장터 API 오류"))
    body = response.get("body") or {}
    try:
        total = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        total = 0
    return G2BPage(_items(body.get("items")), total, page_no, rows)


class G2BClient:
    def __init__(self, *, endpoint: str | None = None, service_key: str | None = None, timeout: int | None = None):
        self.endpoint = str(endpoint or settings.G2B_BID_API_ENDPOINT).rstrip("/")
        self.service_key = str(service_key if service_key is not None else settings.G2B_API_SERVICE_KEY).strip()
        self.timeout = int(timeout or settings.G2B_API_TIMEOUT_SECONDS)
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or parsed.hostname != "apis.data.go.kr":
            raise G2BError("INVALID_ENDPOINT", "허용되지 않은 나라장터 API 주소입니다.")
        if not self.service_key:
            raise G2BError("MISSING_SERVICE_KEY", "G2B_API_SERVICE_KEY가 설정되지 않았습니다.")

    def fetch_page(self, operation: str, start: datetime, end: datetime, *, page_no: int = 1, rows: int = 100) -> G2BPage:
        if operation not in {NOTICE_OPERATION, LICENSE_OPERATION, REGION_OPERATION, BASIS_AMOUNT_OPERATION}:
            raise G2BError("INVALID_OPERATION", "허용되지 않은 나라장터 조회 작업입니다.")
        params = {
            # The portal often provides an encoded key. Decode once before urlencode
            # so both encoded and decoded environment values are accepted safely.
            "serviceKey": unquote(self.service_key),
            "pageNo": max(1, int(page_no)),
            "numOfRows": min(max(1, int(rows)), 999),
            "type": "json",
            "inqryDiv": "1",
            "inqryBgnDt": start.strftime("%Y%m%d%H%M"),
            "inqryEndDt": end.strftime("%Y%m%d%H%M"),
        }
        url = f"{self.endpoint}/{operation}?{urlencode(params)}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "GeoFlow-G2B/1.0"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raise G2BError(f"HTTP_{exc.code}", "나라장터 API HTTP 오류가 발생했습니다.") from exc
        except (URLError, TimeoutError) as exc:
            raise G2BError("NETWORK_ERROR", "나라장터 API에 연결할 수 없습니다.") from exc
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise G2BError("INVALID_JSON", "나라장터 API가 JSON이 아닌 응답을 반환했습니다.") from exc
        return parse_response(payload, page_no=page_no, rows=rows)

    def fetch_all(self, operation: str, start: datetime, end: datetime, *, rows: int = 999) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page_no = 1
        while True:
            page = self.fetch_page(operation, start, end, page_no=page_no, rows=rows)
            result.extend(page.items)
            if not page.items or len(result) >= page.total_count:
                return result
            page_no += 1
            if page_no > 1000:
                raise G2BError("PAGE_LIMIT", "나라장터 API 페이지 안전 한도를 초과했습니다.")
