"""Pure metric segment calculations and the shared central direction contract.

Bearings are clockwise from grid north. Storage/symbol conventions are explicit;
no standard-name, display-name or municipality defaults are inferred.
"""
import math
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

# Operational contract confirmed against the legacy CAD/SQL workflow.
CAD_RULES = dict(zero_axis='east', positive_direction='counterclockwise')
ANGLE_CRS = 'EPSG:5186'


def operational_config(raw):
    """Resolve the approved convention without changing central or stored values."""
    if not isinstance(raw, dict):
        return raw
    return dict(raw, **CAD_RULES, offset=0, ambiguity='longest_uuid')


def quantize_angle(value, decimals=None):
    value = normalize(value)
    if decimals is None:
        return value
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    result = normalize(float(rounded))
    return int(result) if decimals == 0 else result


def normalize(angle):
    angle = float(angle)
    if not math.isfinite(angle):
        raise ValueError("Angle must be finite")
    return angle % 360.0


def validate_rotation(raw):
    """Manual rotation needs only explicit storage/symbol rules, never reference lines."""
    if not isinstance(raw, dict): raise ValueError('방향각 기능의 회전 규칙이 없습니다.')
    required = ('zero_axis','positive_direction','symbol_offset','allow_reverse')
    if any(k not in raw for k in required): raise ValueError('각도 원점·증가 방향·심볼 보정·반전 규칙을 확인하세요.')
    if raw['zero_axis'] not in ('north','east') or raw['positive_direction'] not in ('clockwise','counterclockwise'):
        raise ValueError('각도 원점 또는 증가 방향이 잘못되었습니다.')
    if type(raw['allow_reverse']) is not bool: raise ValueError('반전 허용은 boolean이어야 합니다.')
    value = raw['symbol_offset']
    if isinstance(value,bool) or not math.isfinite(float(value)): raise ValueError('유효한 심볼 보정각이 필요합니다.')
    return dict(zero_axis=raw['zero_axis'],positive_direction=raw['positive_direction'],
                symbol_offset=float(value),allow_reverse=raw['allow_reverse'],offset=0)


def validate_config(raw):
    if not isinstance(raw, dict):
        raise ValueError("Direction settings must be an object")
    result = dict(raw)
    required = {'reference_layer_ids', 'method', 'distance', 'unit', 'offset',
                'allow_reverse', 'ambiguity', 'zero_axis', 'positive_direction',
                'symbol_offset', 'axis_tolerance', 'tie_tolerance'}
    if set(result)-{'require_on_line','diameter_rule'} != required:
        raise ValueError("Direction settings have missing or unknown keys")
    if type(result.get('require_on_line', False)) is not bool:
        raise ValueError('선 일치 여부는 boolean이어야 합니다.')
    rule = result.get('diameter_rule')
    if rule is not None:
        if not isinstance(rule,dict) or set(rule) != {'filter_field_id','filter_value','reference_fields'}:
            raise ValueError('관경 비교 규칙의 필드 설정을 확인하세요.')
        if rule['filter_field_id']:
            UUID(str(rule['filter_field_id']))
            if not str(rule['filter_value']).strip(): raise ValueError('적용할 시설 구분값이 필요합니다.')
        if not isinstance(rule['reference_fields'],dict) or not rule['reference_fields']:
            raise ValueError('기준선별 관경 필드 UUID가 필요합니다.')
        for lid,fid in rule['reference_fields'].items(): UUID(str(lid)); UUID(str(fid))
    refs = result['reference_layer_ids']
    if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
        raise ValueError("Reference layer UUIDs are required and must be unique")
    result['reference_layer_ids'] = [str(UUID(str(x))) for x in refs]
    if result['method'] not in ('connected', 'nearest') or result['unit'] != 'm':
        raise ValueError("Use connected/nearest and metric distances")
    if result['ambiguity'] not in ('review', 'longest_uuid') or type(result['allow_reverse']) is not bool:
        raise ValueError("Ambiguous results require review; allow_reverse must be boolean")
    if result['zero_axis'] not in ('north', 'east') or result['positive_direction'] not in ('clockwise', 'counterclockwise'):
        raise ValueError("Explicit storage angle convention is required")
    for key in ('distance', 'offset', 'symbol_offset', 'axis_tolerance', 'tie_tolerance'):
        if isinstance(result[key], bool):
            raise ValueError("Numeric setting required")
        result[key] = float(result[key])
        if not math.isfinite(result[key]):
            raise ValueError("Finite settings required")
    if not 0 < result['distance'] <= 10000 or not 0 <= result['axis_tolerance'] < 90 or not 0 <= result['tie_tolerance'] <= result['distance']:
        raise ValueError("Invalid distance/axis/tie tolerance")
    return result


def bearing(a, b):
    if a == b:
        raise ValueError("Zero-length segment")
    return normalize(math.degrees(math.atan2(b[0]-a[0], b[1]-a[1])))


def to_storage(value, config):
    value = normalize(value + config['offset'])
    value -= 90 if config['zero_axis'] == 'east' else 0
    return normalize(value if config['positive_direction'] == 'clockwise' else -value)


def to_bearing(value, config):
    value = float(value) * (1 if config['positive_direction'] == 'clockwise' else -1)
    return normalize(value + (90 if config['zero_axis'] == 'east' else 0) - config['offset'])


def symbol_angle(value, config):
    return normalize(to_bearing(value, config) + config['offset'] + config['symbol_offset'])


def project(point, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0.0, min(1.0, ((point[0]-a[0])*dx + (point[1]-a[1])*dy)/(dx*dx+dy*dy)))
    q = (a[0]+t*dx, a[1]+t*dy)
    return q, math.dist(point, q)


def calculate(point, lines, config, reference_metadata=None, angle_transform=None, angle_point=None):
    """lines: (stable reference id, parts of metric XY tuples). Never mutates data."""
    reference_metadata = reference_metadata or {}
    angle_transform = angle_transform or (lambda reference, xy: xy)
    candidates = []
    for reference, parts in lines:
        for part_index, raw in enumerate(parts):
            points = []
            for xy in raw:
                xy = tuple(xy[:2])
                if not all(math.isfinite(v) for v in xy):
                    raise ValueError("Non-finite geometry")
                if not points or xy != points[-1]:
                    points.append(xy)
            if len(points) < 2:
                continue
            if config['method'] == 'nearest':
                segments = [(i, a, b, *project(point, a, b)) for i, (a, b) in enumerate(zip(points, points[1:]))]
            else:
                segments = []
                for i, vertex in enumerate(points):
                    distance = math.dist(point, vertex)
                    if distance > config['distance']:
                        continue
                    # Preserve original vertex order, including at the terminal vertex.
                    neighbors = []
                    if i > 0:
                        neighbors.append((i-1, points[i-1], vertex, vertex, distance))
                    if i+1 < len(points):
                        neighbors.append((i, vertex, points[i+1], vertex, distance))
                    segments.extend(neighbors)
            for index, a, b, projected, distance in segments:
                if distance <= config['distance']:
                    if config.get('require_on_line'):
                        grid_point = angle_point if angle_point is not None else point
                        if project(grid_point,angle_transform(reference,a),angle_transform(reference,b))[1] > 1e-6:
                            continue
                    candidates.append(dict(reference=reference, part=part_index, segment=index,
                        a=a, b=b, point=projected, distance=distance,
                        angle=to_storage(bearing(angle_transform(reference, a), angle_transform(reference, b)), config),
                        segment_length=math.dist(angle_transform(reference, a), angle_transform(reference, b)),
                        **reference_metadata.get(reference,{})))
    if not candidates:
        return dict(status='no_reference', candidates=[])
    minimum = min(c['distance'] for c in candidates)
    if config['method'] == 'nearest':
        candidates = [c for c in candidates if c['distance'] <= minimum+config['tie_tolerance']]
    diameter_reason = ''
    if config.get('diameter_rule'):
        diameters = {}
        for candidate in candidates:
            try:
                value = float(candidate.get('diameter'))
                if not math.isfinite(value) or value <= 0: raise ValueError()
            except (TypeError,ValueError):
                return dict(status='ambiguous',candidates=candidates,angle=None,review_only=True,reason='관경 누락·비숫자·0 이하: 기준선 속성을 확인하세요.')
            diameters[candidate['reference']] = value
        if len(diameters)<2 or min(diameters.values())==max(diameters.values()):
            return dict(status='ambiguous',candidates=candidates,angle=None,review_only=True,reason='서로 다른 관경의 연결 관로 2개 이상이 필요합니다.')
        smallest = min(diameters.values())
        candidates = [c for c in candidates if diameters[c['reference']]==smallest]
        if len({c['reference'] for c in candidates}) != 1:
            return dict(status='ambiguous',candidates=candidates,angle=None,review_only=True,reason='최소 관경의 관로가 여러 개여서 방향 검토가 필요합니다.')
        for c in candidates:
            da, db = math.dist(point,c['a']), math.dist(point,c['b'])
            if min(da,db)>config['distance']+1e-8 or abs(da-db)<1e-8:
                return dict(status='ambiguous',candidates=candidates,angle=None,review_only=True,reason='작은 관경 관로의 접속 끝점을 확인할 수 없습니다.')
            start,end = (c['a'],c['b']) if da<db else (c['b'],c['a'])
            c['angle'] = to_storage(bearing(angle_transform(c['reference'],start),angle_transform(c['reference'],end)),config)
        diameter_reason = f'작은 관경 {smallest:g} 쪽 · '
    if config['ambiguity'] == 'longest_uuid':
        longest = max(c['segment_length'] for c in candidates)
        tied = [c for c in candidates if math.isclose(c['segment_length'], longest, rel_tol=1e-12, abs_tol=1e-6)]
        if len(tied) > 1:
            try:
                for c in tied:
                    c['feature_uuid'] = str(UUID(c.get('feature_uuid', '')))
            except (ValueError, TypeError, AttributeError):
                return dict(status='ambiguous', candidates=candidates, angle=None,
                            reason='동일 길이 후보의 객체 ID가 없어 순서를 결정할 수 없습니다.')
            tied.sort(key=lambda c: (c['feature_uuid'], c.get('layer_uuid',''), c['part'], c['segment']))
        chosen = tied[0]
        rule = '최장 선분' if len(tied) == 1 else '동일 길이 · 객체 ID / 파트 / 선분 순서'
        return dict(status='ok', candidates=candidates, chosen=chosen, angle=chosen['angle'],
                    reason=f"{diameter_reason}{rule} · {chosen['segment_length']:.3f} m · 후보 {len(candidates)}개")
    # Only identical directed tangents on one part coalesce. Opposite directions
    # and even small bends remain reviewable, regardless of axis tolerance.
    unique = []
    for candidate in candidates:
        if any(c['reference'] == candidate['reference'] and c['part'] == candidate['part']
               and math.dist(c['point'], candidate['point']) < 1e-8
               and min(abs(c['angle']-candidate['angle']) % 360,
                       360-abs(c['angle']-candidate['angle']) % 360) < 1e-8 for c in unique):
            continue
        unique.append(candidate)
    return dict(status='ok' if len(unique) == 1 else 'ambiguous', candidates=unique,
                angle=unique[0]['angle'] if len(unique) == 1 else None)
