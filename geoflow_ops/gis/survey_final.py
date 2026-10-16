"""Server-owned Survey method, coordinate interpretation and daily numbering."""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.db import connections

from .qgis_sync import SyncRejected

_EPSG = re.compile(r'^EPSG:(\d{3,6})$', re.I)
_METHODS = {'GNSS': 'GNSS', 'GPS': 'GNSS', 'TOTAL': 'TOTAL_STATION',
            'TOTAL_STATION': 'TOTAL_STATION', 'TOTALSTATION': 'TOTAL_STATION'}
FINAL_FIELDS = ('survey_no', 'type', 'x', 'y', 'z', 'longitude', 'latitude')


def survey_method(value, *, required=False):
    if value in (None, ''):
        return None
    result = _METHODS.get(str(value).strip().upper())
    if result is None and required:
        raise SyncRejected('survey_type must be GNSS or TOTAL_STATION')
    return result


def decimal_input(value, label, *, limit=None):
    if value in (None, ''):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise SyncRejected(f'{label} must be numeric') from exc
    if not result.is_finite() or (limit is not None and abs(result) >= limit):
        raise SyncRejected(f'{label} must be finite and fit its storage type')
    return result


def epsg(value):
    if value in (None, ''):
        return None
    match = _EPSG.fullmatch(str(value).strip())
    if not match:
        raise SyncRejected('Survey CRS must use EPSG:n')
    return int(match.group(1))


def prepare_coordinates(alias, *, project_id, payload, points):
    """Resolve CRS once per batch; retain PostGIS X=Easting, Y=Northing."""
    source_srid = epsg(payload.get('source_crs'))
    target_srid = epsg(payload.get('target_crs'))
    normalized = []
    srids = {4326}
    for srid in (source_srid, target_srid):
        if srid:
            srids.add(srid)
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise SyncRejected(f'points[{index}] must be an object')
        point = dict(point)
        for name, limit in (('raw_x', 10**17), ('raw_y', 10**17), ('raw_z', 10**7)):
            point[name] = decimal_input(point.get(name), f'points[{index}].{name}', limit=limit)
        for name, bound in (('longitude', 180), ('latitude', 90)):
            value = decimal_input(point.get(name), f'points[{index}].{name}')
            if value is not None and abs(value) > bound:
                raise SyncRejected(f'points[{index}].{name} is outside EPSG:4326')
            point[name] = value
        if (point['longitude'] is None) != (point['latitude'] is None):
            raise SyncRejected('longitude and latitude must be supplied together')
        if (point['raw_x'] is None) != (point['raw_y'] is None):
            raise SyncRejected('raw_x and raw_y must be supplied together')
        srid = epsg(point.get('raw_crs')) or source_srid
        if srid:
            srids.add(srid)
        if point['longitude'] is None and (point['raw_x'] is None or srid is None):
            raise SyncRejected('each survey point requires longitude/latitude or raw_x/raw_y with EPSG raw_crs')
        if point['raw_x'] is not None and srid is None:
            raise SyncRejected('raw coordinates require an explicit raw_crs or source_crs')
        point['raw_crs'] = f'EPSG:{srid}' if srid else None
        normalized.append(point)
    with connections[alias].cursor() as c:
        c.execute("SELECT srid,srtext ~ '^PROJ(CS|CRS)\\[' FROM spatial_ref_sys WHERE srid=ANY(%s)", [sorted(srids)])
        projected = dict(c.fetchall())
        if set(srids) - set(projected):
            raise SyncRejected('Survey EPSG CRS is not installed')
        if target_srid and not projected[target_srid]:
            raise SyncRejected('target_crs must be a projected CRS')
        if target_srid is None and source_srid and projected[source_srid]:
            target_srid = source_srid
        needs_target = any(p['raw_x'] is None or not projected.get(epsg(p['raw_crs']), False) for p in normalized)
        if needs_target and target_srid is None:
            # Existing project source metadata is the only automatic fallback.
            # An ambiguous project never silently defaults to a Korean TM zone.
            c.execute("""SELECT DISTINCT COALESCE(src.target_crs,src.source_crs)
                           FROM gis.survey_source src
                           JOIN spatial_ref_sys srs ON
                             ('EPSG:' || srs.srid)=COALESCE(src.target_crs,src.source_crs)
                          WHERE src.project_id=%s AND src.deleted_at IS NULL
                            AND srs.srtext ~ '^PROJ(CS|CRS)\\['""", [project_id])
            candidates = [epsg(row[0]) for row in c.fetchall()]
            if len(candidates) == 1:
                target_srid = candidates[0]
            else:
                raise SyncRejected('geographic Survey input requires target_crs or one unambiguous project planar CRS')
    for point in normalized:
        srid = epsg(point['raw_crs'])
        if srid == 4326 and point['raw_x'] is not None:
            if abs(point['raw_x']) > 180 or abs(point['raw_y']) > 90:
                raise SyncRejected('raw EPSG:4326 coordinates are outside longitude/latitude bounds')
    return normalized, projected, target_srid


def final_xy(point, projected, target_srid):
    srid = epsg(point.get('raw_crs'))
    if point.get('raw_x') is not None and projected.get(srid, False):
        return '%s', [point['raw_x']], '%s', [point['raw_y']]
    return ('ST_X(ST_Transform(geom,%s))', [target_srid],
            'ST_Y(ST_Transform(geom,%s))', [target_srid])


def number_counters(cursor, project_id):
    """Caller holds project_sync_state FOR UPDATE, shared by all GIS writers.

    Include soft-deleted rows and retained number prefixes after a date revision;
    neither deleted nor revised points may cause a number to be reused.
    """
    cursor.execute("""SELECT split_part(survey_no,'-',1),max(split_part(survey_no,'-',2)::bigint)
                        FROM gis.survey WHERE project_id=%s
                         AND survey_no ~ '^[0-9]{6}-[0-9]{3,18}$'
                        GROUP BY split_part(survey_no,'-',1)""", [project_id])
    return defaultdict(int, {str(row[0]): int(row[1]) for row in cursor.fetchall()})


def next_number(counters, survey_date):
    if survey_date is None:
        return None
    if not isinstance(survey_date, dt.date):
        survey_date = dt.date.fromisoformat(str(survey_date))
    prefix = survey_date.strftime('%y%m%d')
    counters[prefix] += 1
    return f'{prefix}-{counters[prefix]:03d}'
