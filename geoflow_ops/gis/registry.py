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
    FeatureType("WTL_ETC_PS", "wtl_etc_ps", "WTL_ETC_PS", "WTL", "POINT"),
    FeatureType("WTL_FIRE_PS", "wtl_fire_ps", "WTL_FIRE_PS", "WTL", "POINT"),
    FeatureType("WTL_FLOW_PS", "wtl_flow_ps", "WTL_FLOW_PS", "WTL", "POINT"),
    FeatureType("WTL_MANH_PS", "wtl_manh_ps", "WTL_MANH_PS", "WTL", "POINT"),
    FeatureType("WTL_PIPE_LM", "wtl_pipe_lm", "WTL_PIPE_LM", "WTL", "LINE"),
    FeatureType("WTL_PIPE_PS", "wtl_pipe_ps", "WTL_PIPE_PS", "WTL", "POINT"),
    FeatureType("WTL_PLAN_LM", "wtl_plan_lm", "WTL_PLAN_LM", "WTL", "LINE"),
    FeatureType("WTL_SPLY_LS", "wtl_sply_ls", "WTL_SPLY_LS", "WTL", "LINE"),
    FeatureType("WTL_VALV_PS", "wtl_valv_ps", "WTL_VALV_PS", "WTL", "POINT"),
    FeatureType("SWL_CONN_LS", "swl_conn_ls", "SWL_CONN_LS", "SWL", "LINE"),
    FeatureType("SWL_ETC_PS", "swl_etc_ps", "SWL_ETC_PS", "SWL", "POINT"),
    FeatureType("SWL_MANH_PS", "swl_manh_ps", "SWL_MANH_PS", "SWL", "POINT"),
    FeatureType("SWL_PIPE_AS", "swl_pipe_as", "SWL_PIPE_AS", "SWL", "LINE"),
    FeatureType("SWL_PIPE_LM", "swl_pipe_lm", "SWL_PIPE_LM", "SWL", "LINE"),
    FeatureType("SWL_PIPE_PS", "swl_pipe_ps", "SWL_PIPE_PS", "SWL", "POINT"),
    FeatureType("SWL_SIDE_LS", "swl_side_ls", "SWL_SIDE_LS", "SWL", "LINE"),
    FeatureType("SWL_SPOT_PS", "swl_spot_ps", "SWL_SPOT_PS", "SWL", "POINT"),
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
