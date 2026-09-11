"""One request for a service-notice count; no notices or cursors are written."""
import json
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError

from geoflow_ops.bids.client import G2BError
from procurement.client import Client, SEARCH, CHANGES
from procurement.policy import SEOUL


class Command(BaseCommand):
    help = "용역 공고 1페이지(1행)의 totalCount와 안전한 오류코드를 점검합니다."

    def add_arguments(self, parser):
        parser.add_argument("--start", required=True, help="한국시각 YYYYMMDDHHMM")
        parser.add_argument("--end", required=True, help="한국시각 YYYYMMDDHHMM")
        parser.add_argument("--mode", choices=("posted", "changed"), default="posted")
        filters = parser.add_mutually_exclusive_group()
        filters.add_argument("--industry")
        filters.add_argument("--keyword")

    def handle(self, **options):
        try:
            start, end = [datetime.strptime(options[k], "%Y%m%d%H%M").replace(tzinfo=SEOUL)
                          for k in ("start", "end")]
            if any(len(options[k]) != 12 for k in ("start", "end")):
                raise ValueError()
        except ValueError:
            raise CommandError("기간은 한국시각 YYYYMMDDHHMM 형식이어야 합니다.") from None
        if end < start or end - start > timedelta(days=1):
            raise CommandError("진단 기간은 시작 이후 최대 1일입니다.")
        if options["mode"] == "changed" and (options["industry"] or options["keyword"]):
            raise CommandError("변경일시 조회는 업종/키워드 검색과 별도로 점검하세요.")
        query = {"inqryDiv": "3" if options["mode"] == "changed" else "1",
                 "inqryBgnDt": options["start"], "inqryEndDt": options["end"]}
        for option, field in (("industry", "indstrytyCd"), ("keyword", "bidNtceNm")):
            if options[option] is not None:
                value = options[option].strip()
                if not value or len(value) > 200:
                    raise CommandError("업종 또는 키워드 값이 올바르지 않습니다.")
                query[field] = value
        operation = CHANGES if options["mode"] == "changed" else SEARCH
        try:
            page = Client(budget=1).page(operation, rows=1, **query)
        except G2BError as exc:
            raise CommandError(f"{exc.code}: {exc}") from None
        self.stdout.write(json.dumps({"operation": operation, "query": query,
                                      "totalCount": page.total_count, "returnedRows": len(page.items),
                                      "requests": 1}, ensure_ascii=False))
