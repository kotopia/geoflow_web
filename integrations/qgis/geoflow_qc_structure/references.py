"""Explicit local code books; immutable revisions and exact, opt-in normalization."""
import json
import os
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile


def normalized(value, trim=False, casefold=False):
    if value is None:
        return None
    value = str(value)
    return (value.strip() if trim else value).casefold() if casefold else (value.strip() if trim else value)


def validate_book(book, trim=False, casefold=False):
    for key in ('id', 'agency', 'business', 'kind', 'mapping_id'):
        if not isinstance(book.get(key), str) or not book[key].strip():
            raise ValueError(f'코드표 필수 정보: {key}')
    codes, aliases = {}, {}
    if not book.get('entries'):
        raise ValueError('코드표 항목이 없습니다.')
    for row in book['entries']:
        for key in ('code', 'name', 'meaning'):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f'코드·명칭·공통 의미 누락: {row}')
        if row['code'] in codes:
            raise ValueError(f"중복 출력 코드: {row['code']}")
        codes[row['code']] = row
        if not isinstance(row.get('aliases'), list):
            raise ValueError('입력 별칭 목록이 필요합니다.')
        for alias in row['aliases']:
            if alias is not None and not isinstance(alias, str):
                raise ValueError('별칭은 문자열 또는 NULL이어야 합니다.')
            key = normalized(alias, trim, casefold)
            if key in aliases:
                raise ValueError(f'입력값 중복/충돌: {alias!r}')
            aliases[key] = row['code']
    return aliases


def convert(value, params):
    if 'book' not in params:  # Existing explicit mappings remain readable.
        mapping = params['mapping']
        if str(value) in mapping:
            return mapping[str(value)]
        if 'fallback' in params:
            return params['fallback']
        raise ValueError(f'미등록 입력값: {value!r}')
    mapping = validate_book(params['book'], params.get('trim', False), params.get('casefold', False))
    key = normalized(value, params.get('trim', False), params.get('casefold', False))
    if key in mapping:
        return mapping[key]
    policy = params.get('unregistered', 'error')
    if policy == 'keep':
        return value
    if policy == 'null':
        return None
    if policy == 'value':
        return params['unregistered_value']
    raise ValueError(f'미등록 입력값: {value!r}')


class CodeBooks:
    def __init__(self, directory):
        self.directory = Path(directory) / 'codebooks'

    def revisions(self):
        result = []
        for path in sorted(self.directory.glob('*.json')):
            book = json.loads(path.read_text(encoding='utf-8'))
            validate_book(book)
            result.append(book)
        return result

    def save(self, book):
        from .catalog import IDENT
        book = deepcopy(book)
        validate_book(book)
        if not IDENT.fullmatch(book['id']):
            raise ValueError('코드표 ID는 영문/숫자/밑줄 식별자여야 합니다.')
        old = [b for b in self.revisions() if b['id'] == book['id']]
        if old and any(book[k] != old[-1][k] for k in ('agency', 'business', 'kind', 'mapping_id')):
            raise ValueError('코드표 범위 변경에는 새 코드표 ID가 필요합니다.')
        book['revision'] = max((b['revision'] for b in old), default=0) + 1
        self.directory.mkdir(parents=True, exist_ok=True)
        dest = self.directory / f"{book['id']}.{book['revision']:09}.json"
        with NamedTemporaryFile('w', encoding='utf-8', dir=self.directory, delete=False) as stream:
            json.dump(book, stream, ensure_ascii=False, indent=2, allow_nan=False)
            temp = Path(stream.name)
        try:
            os.link(temp, dest)
        finally:
            temp.unlink()
        return book


def import_rows(rows, columns):
    """Mapped Excel values; never infer synonym equivalence or numeric code padding."""
    result = []
    for number, row in enumerate(rows, 2):
        if all(v is None or v == '' for v in row):
            continue
        entry = {key: row[index] for key, index in columns.items()}
        if any(not isinstance(entry.get(k), str) for k in ('code', 'name', 'meaning')):
            raise ValueError(f'{number}행: 코드·명칭·의미는 Excel 텍스트 셀이어야 합니다.')
        aliases = entry.get('aliases')
        if aliases in (None, ''):
            entry['aliases'] = []
        elif not isinstance(aliases, str):
            raise ValueError(f'{number}행: 입력 별칭은 텍스트여야 합니다.')
        else:
            entry['aliases'] = json.loads(aliases) if aliases.startswith('[') else [aliases]
        result.append(entry)
    return result


def aggregate_values(items):
    from .qc import numeric
    from decimal import Decimal, localcontext
    unique = dict(items)
    values = [numeric(v) for v in unique.values() if v is not None]
    with localcontext() as ctx:
        ctx.prec = max(50, max((len(v.as_tuple().digits) + abs(v.as_tuple().exponent) for v in values), default=0) + 20)
        return dict(searched=len(unique), valid=len(values), excluded=len(unique)-len(values),
                    sources=list(unique.items()), mean=sum(values, Decimal(0))/len(values) if values else None,
                    minimum=min(values) if values else None, maximum=max(values) if values else None)
