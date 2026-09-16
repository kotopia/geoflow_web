"""Read-only G2B requests. No file downloads and no secret-bearing error strings."""
import json
import hashlib
import time
from xml.etree import ElementTree
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from geoflow_ops.bids.client import G2BError, parse_response
from .policy import minute
from .models import ApiBudget

SEARCH = "getBidPblancListInfoServcPPSSrch"
CHANGES = "getBidPblancListInfoServc"
REGIONS = "getBidPblancListInfoPrtcptPsblRgn"
LICENSES = "getBidPblancListInfoLicenseLimit"
PRODUCTS = "getBidPblancListInfoServcPurchsObjPrdct"

# Do not propagate gateway text: it may echo a request URL containing the key.
ERROR_MESSAGES = {
    "10": "요청 파라미터 이름·형식·허용값을 확인하세요.",
    "12": "API 주소 또는 서비스 제공 여부를 확인하세요.",
    "20": "인증키 전달 및 해당 서비스 활용승인 상태를 확인하세요.",
    "22": "일일 API 호출 허용량을 초과했습니다.",
    "23": "초당 API 호출 허용량을 초과했습니다.",
    "29": "호출 IP의 접근 상태를 확인하세요.",
    "30": "인증키 등록 및 서비스 활용신청 상태를 확인하세요.",
    "31": "API 이용기간을 확인하세요.",
}


def response_error(raw, fallback):
    """Extract only a numeric code from bounded JSON/XML gateway responses."""
    code = None
    try:
        payload = json.loads(raw)
        code = payload["response"]["header"]["resultCode"]
    except (ValueError, TypeError, KeyError):
        try:
            if b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper():
                root = ElementTree.fromstring(raw)
                code = next((node.text for node in root.iter()
                             if node.tag.rsplit("}", 1)[-1] in {"returnReasonCode", "resultCode"}), None)
        except ElementTree.ParseError:
            pass
    code = str(code or "")
    if code.isascii() and code.isdigit() and 1 <= len(code) <= 3 and int(code) != 0:
        code = str(int(code)).zfill(2)
        return G2BError("API_" + code, ERROR_MESSAGES.get(code, "나라장터 API 오류입니다."))
    return G2BError(fallback, "나라장터 응답 상태 또는 형식을 확인하세요.")


class Client:
    def __init__(self, budget=100):
        self.budget = budget
        self.checkpoint = None
        self.save_checkpoint = None
        self.deadline = None
        self.next_request_at = 0
        self.scope_check = None

    def pace(self):
        if self.scope_check:
            self.scope_check()
        now = time.monotonic()
        delay = max(0, self.next_request_at - now)
        if self.deadline is not None and now + delay + 30 >= self.deadline:
            raise G2BError("TIME_BUDGET_EXHAUSTED", "작업 시간 예산에 도달하여 다음 실행에서 이어갑니다.")
        if delay:
            time.sleep(delay)
        self.next_request_at = time.monotonic() + max(0, min(10, getattr(settings, "G2B_REQUEST_INTERVAL_SECONDS", 1)))

    def bind_checkpoint(self, progress, save):
        self.checkpoint = progress
        self.save_checkpoint = save

    def _save(self):
        if self.save_checkpoint:
            self.checkpoint["updated_at"] = timezone.now().isoformat()
            self.save_checkpoint()

    def reserve(self):
        alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        day = minute(timezone.now()).date()
        with transaction.atomic(using=alias):
            ApiBudget.objects.using(alias).get_or_create(day=day)
            counter = ApiBudget.objects.using(alias).select_for_update().get(day=day)
            if counter.used >= getattr(settings, "G2B_CENTRAL_DAILY_BUDGET", 500):
                raise G2BError("DAILY_BUDGET_EXHAUSTED", "중앙 수집 일일 호출 예산에 도달했습니다.")
            counter.used += 1
            counter.save(using=alias, update_fields=["used"])

    def page(self, operation, *, page_no=1, rows=999, **query):
        if operation not in {SEARCH, CHANGES, REGIONS, LICENSES, PRODUCTS}:
            raise G2BError("INVALID_OPERATION", "허용되지 않은 조회입니다.")
        key = str(getattr(settings, "G2B_API_SERVICE_KEY", "")).strip()
        if not key:
            raise G2BError("MISSING_SERVICE_KEY", "나라장터 인증키 설정이 필요합니다.")
        if self.budget <= 0:
            raise G2BError("BUDGET_EXHAUSTED", "이번 작업의 호출 한도에 도달했습니다.")
        self.pace()
        self.budget -= 1
        self.reserve()
        params = dict(query, serviceKey=unquote(key), type="json", pageNo=page_no, numOfRows=rows)
        request = Request(
            "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/" + operation + "?" + urlencode(params),
            headers={"Accept": "application/json", "User-Agent": "GeoFlow-G2B/2.0"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                raw = exc.read(65536)
            except (OSError, ValueError):
                raw = b""
            finally:
                exc.close()
            raise response_error(raw, f"HTTP_{exc.code}") from None
        except (URLError, TimeoutError):
            raise G2BError("NETWORK_ERROR", "나라장터 연결 오류") from None
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            raise response_error(raw[:65536], "INVALID_RESPONSE") from None
        try:
            page = parse_response(payload, page_no=page_no, rows=rows)
        except (G2BError, AttributeError, TypeError):
            raise response_error(raw[:65536], "INVALID_RESPONSE") from None
        try:
            total = payload["response"]["body"]["totalCount"]
            if isinstance(total, bool) or not str(total).isascii() or not str(total).isdigit():
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise G2BError("INVALID_TOTAL", "전체 결과 건수를 확인할 수 없습니다.") from None
        if len(page.items) > rows or len(page.items) > page.total_count:
            raise G2BError("INVALID_TOTAL", "응답 건수가 전체 결과 건수와 일치하지 않습니다.")
        body = payload["response"]["body"]
        for field, expected in (("pageNo", page_no), ("numOfRows", rows)):
            if field in body and str(body[field]) != str(expected):
                raise G2BError("PAGE_METADATA_MISMATCH", "응답 페이지 정보가 요청과 다릅니다.")
        ApiBudget.objects.using(getattr(settings, "CENTRAL_DB_ALIAS", "default")).filter(
            day=minute(timezone.now()).date()).update(received=F("received") + len(page.items))
        return page

    def all(self, operation, **query):
        rows = 999
        query_key = hashlib.sha256(json.dumps([operation, query, rows], sort_keys=True).encode()).hexdigest()
        cache = self.checkpoint.setdefault("api_page_cache", {}) if self.checkpoint is not None else {}
        state = cache.setdefault(query_key, dict(operation=operation, query=query, numOfRows=rows,
                                                 totalCount=None, pages=[], complete=False))
        result = [item for page in state["pages"] for item in page["items"]]
        if state["complete"]:
            return result
        page_no = len(state["pages"]) + 1
        while True:
            if page_no > 1000:
                raise G2BError("PAGE_LIMIT_EXCEEDED", "구간 분할 또는 페이지 검토가 필요합니다.")
            page = self.page(operation, page_no=page_no, rows=rows, **query)
            digest = hashlib.sha256(json.dumps(page.items, sort_keys=True).encode()).hexdigest()
            code = None
            if state["totalCount"] is not None and state["totalCount"] != page.total_count:
                code = "TOTAL_CHANGED"
            elif page.items and any(p["digest"] == digest for p in state["pages"]):
                code = "REPEATED_PAGE"
            elif len(result) + len(page.items) > page.total_count:
                code = "INVALID_TOTAL"
            elif not page.items and len(result) < page.total_count:
                code = "INCOMPLETE_RESPONSE"
            if code:
                cache.pop(query_key, None)
                self._save()
                raise G2BError(code, "페이지 수량이 일치하지 않아 해당 조회를 다시 확인합니다.")
            result.extend(page.items)
            state["totalCount"] = page.total_count
            state["pages"].append(dict(pageNo=page_no, received=len(page.items), digest=digest, items=page.items))
            state["complete"] = len(result) == page.total_count
            self._save()
            if state["complete"]:
                return result
            page_no += 1

    def search(self, rule, start, end):
        field = "indstrytyCd" if rule.kind == "industry" else "bidNtceNm"
        return self.all(SEARCH, inqryDiv="1", inqryBgnDt=minute(start).strftime("%Y%m%d%H%M"),
                        inqryEndDt=minute(end).strftime("%Y%m%d%H%M"), **{field: rule.value})

    def changes(self, start, end):
        return self.all(CHANGES, inqryDiv="3", inqryBgnDt=minute(start).strftime("%Y%m%d%H%M"),
                        inqryEndDt=minute(end).strftime("%Y%m%d%H%M"))

    def details(self, row):
        query = dict(inqryDiv="2", bidNtceNo=row["bidNtceNo"], bidNtceOrd=row.get("bidNtceOrd") or "00")
        return {"regions": self.all(REGIONS, **query), "industries": self.all(LICENSES, **query),
                "products": self.all(PRODUCTS, **query)}
