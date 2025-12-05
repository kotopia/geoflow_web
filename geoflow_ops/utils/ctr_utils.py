# geoflow_ops/utils/ctr_utils.py
import re
from django.db.models import Max
from control.middleware import current_db_alias
from geoflow_ops.models import Contract  # 모델 경로 필요 시 조정

ALNUM_RE = re.compile(r'([A-Za-z]*)([0-9]+)$')

def _bump_alnum(s: str) -> str:
    """
    '25019' -> '25020', 'A009' -> 'A010', 'CN-99Z' 같은 비정형은 마지막 문자 기준 점진 증가.
    """
    s = (s or "").strip()
    m = ALNUM_RE.search(s)
    if m:
        prefix, num = m.groups()
        new_num = str(int(num) + 1).zfill(len(num))
        return f"{prefix}{new_num}"

    if s.isdigit():
        return str(int(s) + 1)

    if not s:
        return "1"
    last = s[-1]
    if '0' <= last <= '8':
        return s[:-1] + chr(ord(last) + 1)
    if last == '9':
        return s + '0'
    if 'A' <= last <= 'Y' or 'a' <= last <= 'y':
        return s[:-1] + chr(ord(last) + 1)
    if last in ('Z', 'z'):
        return s + ('A' if last == 'Z' else 'a')
    return s + 'A'

def next_contract_code(alias: str | None = None) -> str:
    """
    현 테넌트 DB에서 다음 계약번호를 제안.
    - 숫자 코드가 있으면 최댓값 + 1
    - 없으면 사전순 MAX를 기반으로 알파뉴메릭 증가
    - 비어있으면 '25001'부터 시작 (원하면 변경)
    """
    alias = alias or current_db_alias()
    qs = Contract.objects.using(alias).all().only('code')
    if not qs.exists():
        return "25001"

    # 숫자 코드 최댓값
    max_numeric = None
    for c in qs:
        code = (c.code or "").strip()
        if code.isdigit():
            v = int(code)
            if (max_numeric is None) or (v > max_numeric):
                max_numeric = v
    if max_numeric is not None:
        return str(max_numeric + 1)

    # 알파뉴메릭: 사전순 MAX 선택 후 증가
    max_code = qs.aggregate(m=Max('code'))['m']
    return _bump_alnum(max_code or "1")
