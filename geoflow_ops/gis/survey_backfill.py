"""Idempotent final-field backfill, with normal project locks/revisions/receipts."""
from __future__ import annotations

import uuid
import json
from collections import Counter

from django.db import connections, transaction

from .changeset import (_allocate_revisions, _complete_receipt, _ensure_project_state,
                        _insert_change_log, _plain_value, _reserve_receipt)
from .survey_final import FINAL_FIELDS, next_number, number_counters, survey_method

# Preserve original input, sources, identities, geometry and all normal final values.
_FIELDS = ('source_id', 'source_row_id', 'raw_x', 'raw_y', 'raw_z', 'raw_crs',
           'raw_code', 'raw_geoid_model', 'worker_id', 'survey_date', 'name', 'code',
           'solution_info', 'pdop', 'antenna_height', 'raw_data', *FINAL_FIELDS)


def backfill_survey_project(alias, project_id):
    counts = Counter()
    with transaction.atomic(using=alias):
        _ensure_project_state(alias, project_id)
        with connections[alias].cursor() as c:
            counters = number_counters(c, project_id)
            c.execute("""SELECT DISTINCT srs.srid FROM gis.survey_source src
                          JOIN spatial_ref_sys srs ON ('EPSG:' || srs.srid)=COALESCE(src.target_crs,src.source_crs)
                         WHERE src.project_id=%s AND src.deleted_at IS NULL
                           AND srs.srtext ~ '^PROJ(CS|CRS)\\['""", [project_id])
            targets = [r[0] for r in c.fetchall()]
            fallback = targets[0] if len(targets) == 1 else None
            c.execute("""SELECT s.id::text,ST_AsBinary(s.geom),
                         s.source_id::text,s.source_row_id,s.raw_x,s.raw_y,s.raw_z,
                         s.raw_crs,s.raw_code,s.raw_geoid_model,s.worker_id::text,
                         s.survey_date,s.name,s.code,s.solution_info,s.pdop,s.antenna_height,s.raw_data,
                         s.survey_no,s.type,s.x,s.y,s.z,s.longitude,s.latitude,
                         src.survey_type,src.source_type,
                         CASE WHEN srs.srtext ~ '^PROJ(CS|CRS)\\[' THEN true ELSE false END,
                         ST_X(s.geom),ST_Y(s.geom),
                         ST_X(ST_Transform(s.geom, CASE WHEN target_srs.srtext ~ '^PROJ(CS|CRS)\\[' THEN target_srs.srid ELSE %s END)),
                         ST_Y(ST_Transform(s.geom, CASE WHEN target_srs.srtext ~ '^PROJ(CS|CRS)\\[' THEN target_srs.srid ELSE %s END))
                    FROM gis.survey s LEFT JOIN gis.survey_source src ON src.id=s.source_id
                    LEFT JOIN spatial_ref_sys srs ON ('EPSG:' || srs.srid)=COALESCE(s.raw_crs,src.source_crs)
                    LEFT JOIN spatial_ref_sys target_srs ON ('EPSG:' || target_srs.srid)=COALESCE(src.target_crs,src.source_crs)
                   WHERE s.project_id=%s
                   ORDER BY s.survey_date,s.created_at,s.id FOR UPDATE OF s""", [fallback, fallback, project_id])
            rows = c.fetchall()
        events = []
        for row in rows:
            values = dict(zip(_FIELDS, row[2:25]))
            if isinstance(values['raw_data'], str):
                values['raw_data'] = json.loads(values['raw_data'])
            old = _plain_value(values)
            if not values['survey_no']:
                number = next_number(counters, values['survey_date'])
                if number:
                    values['survey_no'] = number
                    counts['survey_no'] += 1
                else:
                    counts['missing_date'] += 1
            if values['type'] is None:
                raw_data = values['raw_data'] or {}
                methods = {method for method in (
                    survey_method(row[25]), survey_method(row[26]),
                    survey_method(raw_data.get('survey_type')),
                    survey_method(raw_data.get('method')),
                ) if method}
                if len(methods) == 1:
                    values['type'] = methods.pop()
                    counts['type'] += 1
                else:
                    counts['unknown_method'] += 1
            if row[27]:
                for final, raw in (('x','raw_x'), ('y','raw_y')):
                    if values[final] is None and values[raw] is not None:
                        values[final] = values[raw]
                        counts[final] += 1
            else:
                for final, raw, derived in (('x', 'raw_x', row[30]), ('y', 'raw_y', row[31])):
                    copied_degrees = values['raw_crs'] == 'EPSG:4326' and values[final] == values[raw]
                    if values[final] is None or copied_degrees:
                        if derived is not None:
                            values[final] = derived
                            counts[final] += 1
                        else:
                            counts['unresolved_'+final] += 1
            # There is no zero DB default in the surveyed live schema. A real
            # zero must therefore be retained, including elevation and antenna.
            if values['z'] is None and values['raw_z'] is not None:
                values['z'] = values['raw_z']
                counts['z'] += 1
            for name, geom_value in (('longitude', row[28]), ('latitude', row[29])):
                if values[name] is None and geom_value is not None:
                    values[name] = geom_value
                    counts[name] += 1
            new = _plain_value(values)
            changed = [key for key in FINAL_FIELDS if old[key] != new[key]]
            if not changed:
                continue
            with connections[alias].cursor() as c:
                c.execute("""UPDATE gis.survey SET survey_no=%s,type=%s,x=%s,y=%s,z=%s,
                                  longitude=%s,latitude=%s,updated_at=now()
                              WHERE project_id=%s AND id=%s""",
                          [*(values[key] for key in FINAL_FIELDS), project_id, row[0]])
            events.append((row[0], row[1], changed, old, new))
        if events:
            client_id, changeset_id = str(uuid.uuid4()), str(uuid.uuid4())
            if not _reserve_receipt(alias, project_id=project_id, client_id=client_id,
                                    changeset_id=changeset_id, actor_ref='survey_final_backfill',base_revision=None):
                raise RuntimeError('Survey backfill receipt unavailable')
            first, last, current = _allocate_revisions(alias, project_id, len(events))
            for offset, (object_id, geom, changed, old, new) in enumerate(events):
                _insert_change_log(alias, project_id=project_id, revision=first+offset,
                    changeset_id=changeset_id, client_id=client_id,standard_name='SURVEY',
                    physical_name='survey',object_id=object_id,action='update',
                    changed_fields=changed,old_values=old,new_values=new,
                    geom_before=bytes(geom) if geom else None,geom_after=bytes(geom) if geom else None,
                    actor_ref='survey_final_backfill')
            _complete_receipt(alias, project_id=project_id,client_id=client_id,changeset_id=changeset_id,
                first_revision=first,last_revision=last,change_count=len(events),
                response={'ok':True,'backfilled':len(events),'current_revision':current})
        counts['updated'] = len(events)
        counts['examined'] = len(rows)
    return dict(counts)
