"""Read-only G2B requests. No file downloads and no secret-bearing error strings."""
import json
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

    def all(self, operation, **query):
        if operation not in {SEARCH, CHANGES, REGIONS, LICENSES, PRODUCTS}:
            raise G2BError("INVALID_OPERATION", "허용되지 않은 조회입니다.")
        key = str(getattr(settings, "G2B_API_SERVICE_KEY", "")).strip()
        if not key:
            raise G2BError("MISSING_SERVICE_KEY", "나라장터 인증키 설정이 필요합니다.")
        result = []
        page_no = 1
        while True:
            if self.budget <= 0:
                raise G2BError("BUDGET_EXHAUSTED", "이번 작업의 호출 한도에 도달했습니다.")
            self.budget -= 1
            self.reserve()
            params = dict(query, serviceKey=unquote(key), type="json", pageNo=page_no, numOfRows=999)
            request = Request(
                "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/" + operation + "?" + urlencode(params),
                headers={"Accept": "application/json", "User-Agent": "GeoFlow-G2B/2.0"},
            )
            try:
                with urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8-sig"))
            except HTTPError as exc:
                raise G2BError(f"HTTP_{exc.code}", "나라장터 HTTP 응답 오류") from None
            except (URLError, TimeoutError):
                raise G2BError("NETWORK_ERROR", "나라장터 연결 오류") from None
            except (ValueError, UnicodeError):
                raise G2BError("INVALID_RESPONSE", "나라장터 응답 형식 오류") from None
            page = parse_response(payload, page_no=page_no, rows=999)
            try:
                total = int(payload["response"]["body"]["totalCount"])
                if total < 0:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise G2BError("INVALID_TOTAL", "전체 결과 건수를 확인할 수 없습니다.") from None
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
