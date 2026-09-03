"""GeoFlow GIS initial feature registry.

This registry is intentionally code-only in the first foundation increment.
It mirrors the initial table *kinds* agreed from DB테이블--.xlsx without
pretending that every physical field/geometry detail is already finalized.
The durable source of truth will move to gis.meta_feature_type/profile tables
once the tenant GIS schema is rehearsed and approved.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureType:
    standard_name: str
    physical_name: str
    label: str
    domain: str
    geometry_kind: str
    role: str = "ASSET"
    scope_type: str = "PROJECT"
    initial: bool = True


FEATURE_TYPES = (
    FeatureType("DORO", "doro", "도로 기준", "COMMON", "LINE", "SURVEY_REFERENCE"),
    FeatureType("SURVEY", "survey", "공통 측량", "COMMON", "POINT", "SURVEY_OBSERVATION"),
    FeatureType("WTL_ETC_PS", "wtl_etc_ps", "상수 기타시설", "WTL", "POINT"),
    FeatureType("WTL_FIRE_PS", "wtl_fire_ps", "소화전", "WTL", "POINT"),
    FeatureType("WTL_FLOW_PS", "wtl_flow_ps", "유량계", "WTL", "POINT"),
    FeatureType("WTL_MANH_PS", "wtl_manh_ps", "상수 맨홀", "WTL", "POINT"),
    FeatureType("WTL_PIPE_LM", "wtl_pipe_lm", "상수관로", "WTL", "LINE"),
    FeatureType("WTL_PIPE_PS", "wtl_pipe_ps", "상수 관로측점", "WTL", "POINT"),
    FeatureType("WTL_PLAN_LM", "wtl_plan_lm", "계획/기준 관로", "WTL", "LINE"),
    FeatureType("WTL_SPLY_LS", "wtl_sply_ls", "급수관로", "WTL", "LINE"),
    FeatureType("WTL_VALV_PS", "wtl_valv_ps", "변류시설", "WTL", "POINT"),
    FeatureType("SWL_CONN_LS", "swl_conn_ls", "하수 연결관", "SWL", "LINE"),
    FeatureType("SWL_ETC_PS", "swl_etc_ps", "하수 기타시설", "SWL", "POINT"),
    FeatureType("SWL_MANH_PS", "swl_manh_ps", "하수 맨홀", "SWL", "POINT"),
    FeatureType("SWL_PIPE_AS", "swl_pipe_as", "하수 관로 보조선", "SWL", "LINE"),
    FeatureType("SWL_PIPE_LM", "swl_pipe_lm", "하수관로", "SWL", "LINE"),
    FeatureType("SWL_PIPE_PS", "swl_pipe_ps", "하수 관로측점", "SWL", "POINT"),
    FeatureType("SWL_SIDE_LS", "swl_side_ls", "측구", "SWL", "LINE"),
    FeatureType("SWL_SPOT_PS", "swl_spot_ps", "물받이", "SWL", "POINT"),
)

DOMAIN_LABELS = {
    "COMMON": "공통",
    "WTL": "상수",
    "SWL": "하수",
}


def feature_rows():
    return [
        {
            "standard_name": item.standard_name,
            "physical_name": item.physical_name,
            "db_name": f"gis.{item.physical_name}",
            "label": item.label,
            "domain": item.domain,
            "domain_label": DOMAIN_LABELS.get(item.domain, item.domain),
            "geometry_kind": item.geometry_kind,
            "role": item.role,
            "scope_type": item.scope_type,
        }
        for item in FEATURE_TYPES
    ]


def domain_counts():
    counts = {key: 0 for key in DOMAIN_LABELS}
    for item in FEATURE_TYPES:
        counts[item.domain] = counts.get(item.domain, 0) + 1
    return [
        {"code": key, "label": DOMAIN_LABELS[key], "count": counts.get(key, 0)}
        for key in DOMAIN_LABELS
    ]
