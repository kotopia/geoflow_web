"""Read-only G2B requests. No file downloads and no secret-bearing error strings."""
import json
from xml.etree import ElementTree
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
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
        return page

    def all(self, operation, **query):
        result = []
        page_no = 1
        while True:
            page = self.page(operation, page_no=page_no, **query)
            result.extend(page.items)
            if len(result) >= page.total_count:
                return result
            if not page.items or page_no >= 1000:
                raise G2BError("INCOMPLETE_RESPONSE", "전체 페이지를 받지 못했습니다.")
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
