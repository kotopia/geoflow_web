"""Survey import row review and contract-v1 point metadata shaping."""
from collections import Counter
from datetime import date, datetime
import json
import math
from uuid import UUID
from .import_file import build_import


def metadata_candidates(headers):
    aliases = {
        'name': ('이름', 'name'), 'code': ('코드', 'code'),
        'survey_date': ('현재날짜', '측량일', 'date', 'survey_date'),
        # Survey Height is the same deployed value as antenna_height.
        'antenna_height': ('survey_height', 'height', '측고', '장비높이',
                           '수신기높이', '안테나높이', 'antenna_height',
                           'antenna height'),
        'pdop': ('pdop',), 'solution_info': ('solution', 'solution_info'),
        'raw_data': ('raw_data',),
        'raw_geoid_model': ('raw_geoid_model', 'geoid_model'),
    }
    normalized = {str(h).strip().casefold(): h for h in headers}
    return {key: next((normalized[a] for a in names if a in normalized), None)
            for key, names in aliases.items()}


def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def point_metadata(row, *, worker_id=None, default_date=None, consumed_columns=(),
                   mapped_columns=None):
    """Build only the point keys allowed by the deployed Survey contract."""
    result = {}
    if worker_id:
        result['worker_id'] = str(UUID(str(worker_id)))
    columns = metadata_candidates(row.keys())
    columns.update({
        key: value for key, value in (mapped_columns or {}).items()
        if key in columns and value
    })
    survey_date = local_date(row.get(columns['survey_date']) if columns['survey_date'] else None,
                             default_date)
    if survey_date:
        result['survey_date'] = survey_date
    for key in ('name', 'code', 'solution_info', 'raw_geoid_model'):
        column = columns.get(key)
        value = row.get(column) if column else None
        if value is not None and str(value).strip():
            text = str(value).strip()
            maximum = {'name': 30, 'code': 30, 'solution_info': 200}.get(key)
            if maximum is not None and len(text) > maximum:
                raise ValueError(f'{key} 값은 {maximum}자를 넘을 수 없습니다.')
            result[key] = text
    for key in ('pdop', 'antenna_height'):
        column = columns.get(key)
        value = row.get(column) if column else None
        if value is None or str(value).strip() == '':
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f'{key} 값 {value!r}: 숫자가 아닙니다.') from None
        if not math.isfinite(number) or number < 0:
            raise ValueError(f'{key} 값 {value!r}: 0 이상의 유한한 숫자가 아닙니다.')
        result[key] = number

    raw_data = {}
    raw_column = columns.get('raw_data')
    raw_value = row.get(raw_column) if raw_column else None
    if raw_value not in (None, ''):
        if isinstance(raw_value, dict):
            raw_data.update(raw_value)
        else:
            try:
                parsed = json.loads(str(raw_value))
            except (TypeError, ValueError):
                raise ValueError('raw_data 값은 JSON object여야 합니다.') from None
            if not isinstance(parsed, dict):
                raise ValueError('raw_data 값은 JSON object여야 합니다.')
            raw_data.update(parsed)
    known = set(consumed_columns) | {column for column in columns.values() if column}
    for column in row.keys():
        value = row.get(column)
        if column not in known and value not in (None, ''):
            raw_data[str(column)] = _json_value(value)
    if raw_data:
        result['raw_data'] = raw_data
    return result


def local_date(value, default=None):
    if value is None or str(value).strip() == '':
        return default
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value).strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f'측량일 값 {value!r}: YYYY-MM-DD 날짜를 확인하세요.')


def duplicate_status(point, existing, source_group_id=None, source_crs=''):
    """Only exact unchanged rows in the SAME lineage are auto-excluded.

    An identifier match across sources or any changed/missing evidence remains
    POSSIBLE_DUPLICATE. No tolerance, reprojection or coordinate rounding.
    """
    matches = [row for row in existing if str(row.get('source_row_id', '')) == point['source_row_id']]
    for row in matches:
        if not source_group_id or str(row.get('source_group_id', '')) != source_group_id:
            continue
        if not source_crs or str(row.get('raw_crs') or row.get('source_crs') or '') != source_crs:
            continue
        keys = set(point) - {'source_row_id'}
        if not keys or any(key not in row or row[key] != point[key] for key in keys):
            continue
        # Missing incoming height/code must not erase changed observations.
        if any(key not in point and row.get(key) not in (None, '') for key in ('raw_z', 'raw_code')):
            continue
        return 'DUPLICATE'
    return 'POSSIBLE_DUPLICATE' if matches else 'NEW'


def review_rows(rows, mapping, options, existing=(), worker_id=None,
                default_date=None, mapped_columns=None):
    ids = Counter(str(row.get(mapping.get('source_row_id')) or '').strip() for row in rows)
    result = []
    for row in rows:
        try:
            payload = build_import([row], mapping, **options)
            point = payload['points'][0]
            if ids[point['source_row_id']] > 1:
                raise ValueError(f"{row.number}행 · source_row_id {point['source_row_id']!r}: 파일 내 중복입니다.")
            comparison = {**point, **point_metadata(
                # A UI fallback date is not source evidence for duplicate
                # detection; explicit row dates remain part of comparison.
                row, worker_id=worker_id, default_date=None,
                consumed_columns={column for column in mapping.values() if column},
                mapped_columns=mapped_columns)}
            state = duplicate_status(comparison, existing, options.get('source_group_id'), options.get('source_crs', ''))
            result.append(dict(row=row, point=point, state=state, checked=state != 'DUPLICATE', error=''))
        except ValueError as exc:
            result.append(dict(row=row, point=None, state='ERROR', checked=False, error=str(exc)))
    return result
