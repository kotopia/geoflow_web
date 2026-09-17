"""Read-only central layer registry shared by Web GIS, QGIS and QField."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureType:
    id: str
    standard_name: str
    physical_name: str
    label: str
    domain: str
    geometry_kind: str
    role: str = 'ASSET'
    scope_type: str = 'PROJECT'


# No code-side layer definitions. Kept as an empty import sentinel for older
# extension modules; runtime callers must use feature_rows/feature_by_name.
FEATURE_TYPES=()
DOMAIN_LABELS={'COMMON':'공통','WTL':'상수','SWL':'하수'}


def _features():
    from .central_definitions import central_snapshot
    data=central_snapshot() or {}
    return [FeatureType(id=row['id'],standard_name=row['standard_name'],physical_name=row['physical_name'],
        label=row['label'],domain=row.get('domain_code',''),geometry_kind=row.get('geometry_kind',''),
        role=row.get('feature_role','ASSET'),scope_type=row.get('scope_type','PROJECT'))
        for row in data.get('layers',[]) if row.get('active')]


def feature_by_name(value):
    key=str(value or '').strip().upper()
    return next((item for item in _features() if key in (item.standard_name.upper(),item.physical_name.upper())),None)


def feature_rows():
    return [{'id':item.id,'standard_name':item.standard_name,'physical_name':item.physical_name,
        'db_name':'gis.'+item.physical_name,'label':item.label,'domain':item.domain,
        'domain_label':DOMAIN_LABELS.get(item.domain,item.domain),'geometry_kind':item.geometry_kind,
        'role':item.role,'scope_type':item.scope_type} for item in _features()]


def domain_counts():
    return domain_counts_for_rows(feature_rows())


def domain_counts_for_rows(rows):
    counts={}
    for row in rows:
        code=str(row.get('domain') or '').upper()
        if code: counts[code]=counts.get(code,0)+1
    return [{'code':code,'label':DOMAIN_LABELS.get(code,code),'count':count} for code,count in counts.items()]
