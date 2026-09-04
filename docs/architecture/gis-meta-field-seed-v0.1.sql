-- GeoFlow GIS meta_field_def seed v0.1
-- DEVELOPMENT / PILOT ONLY.
-- Derives field metadata from the actual initial gis physical tables so metadata
-- remains synchronized with physical columns. Run only in dev/test DBs.

BEGIN;

DO $$
DECLARE
    db_name text := current_database();
BEGIN
    IF db_name !~* '(dev|test)' THEN
        RAISE EXCEPTION 'Safety stop: GIS metadata seed may run only in a dev/test database. Current DB=%', db_name;
    END IF;
    IF to_regclass('gis.meta_feature_type') IS NULL OR to_regclass('gis.meta_field_def') IS NULL THEN
        RAISE EXCEPTION 'GIS metadata foundation tables are missing.';
    END IF;
END
$$;

-- Refresh only metadata for registered initial physical feature tables. UUIDs are
-- deterministic so repeated runs update the same logical field definitions.
INSERT INTO gis.meta_field_def (
    id,
    feature_type_id,
    standard_name,
    physical_name,
    label,
    data_type,
    unit,
    code_group_key,
    widget_type,
    required_default,
    core_field,
    sort_order,
    description
)
SELECT
    md5(ft.id::text || ':' || c.column_name)::uuid AS id,
    ft.id AS feature_type_id,
    upper(c.column_name) AS standard_name,
    c.column_name AS physical_name,
    upper(c.column_name) AS label,
    CASE
        WHEN c.udt_name = 'geometry' THEN 'geometry'
        WHEN c.data_type = 'USER-DEFINED' THEN c.udt_name
        ELSE c.data_type
    END AS data_type,
    CASE
        WHEN c.column_name ~ '(_dep|_dist|_len|topi|dpg_dep)$' THEN 'm'
        WHEN c.column_name ~ '(_dip|_std|_size|_size_h|_size_v|_std_h|_std_v|_std_d)$' THEN 'mm'
        ELSE NULL
    END AS unit,
    CASE c.column_name
        WHEN 'ftr_cde' THEN ft.domain_code || '.FTR_CDE'
        WHEN 'cst_cde' THEN ft.domain_code || '.CST_CDE'
        WHEN 'off_cde' THEN ft.domain_code || '.OFF_CDE'
        WHEN 'mop_cde' THEN ft.domain_code || '.MOP_CDE'
        WHEN 'saa_cde' THEN ft.domain_code || '.SAA_CDE'
        WHEN 'iqt_cde' THEN ft.domain_code || '.IQT_CDE'
        WHEN 'jht_cde' THEN ft.domain_code || '.JHT_CDE'
        WHEN 'val_mof' THEN 'WTL.VAL_MOF'
        WHEN 'val_mop' THEN 'WTL.VAL_MOP'
        WHEN 'val_for' THEN 'WTL.VAL_FOR'
        ELSE NULL
    END AS code_group_key,
    CASE
        WHEN c.column_name = 'geom' THEN 'map'
        WHEN c.column_name = 'project_id' THEN 'project_relation'
        WHEN c.column_name IN ('description') THEN 'textarea'
        WHEN c.column_name IN ('ext_data') THEN 'json'
        WHEN c.data_type = 'date' THEN 'date'
        WHEN c.data_type LIKE 'timestamp%' THEN 'datetime'
        WHEN c.data_type IN ('numeric','double precision','real','integer','bigint','smallint') THEN 'number'
        WHEN c.column_name LIKE '%_cde' OR c.column_name IN ('val_mof','val_mop','val_for') THEN 'select'
        ELSE 'text'
    END AS widget_type,
    (c.column_name = 'id') AS required_default,
    (c.column_name IN (
        'id','project_id','ftr_cde','ftr_idn','geom','ist_ymd',
        'created_at','updated_at','created_by','updated_by'
    )) AS core_field,
    c.ordinal_position AS sort_order,
    CASE c.column_name
        WHEN 'id' THEN 'GeoFlow internal UUID primary key. Authoritative object identity.'
        WHEN 'ftr_idn' THEN 'Optional external/municipal facility identifier. Not used as GeoFlow internal identity.'
        WHEN 'gid' THEN 'Optional legacy/source row identifier.'
        WHEN 'project_id' THEN 'GeoFlow project UUID reference.'
        WHEN 'ext_data' THEN 'Sparse/source-specific values not yet promoted to physical columns.'
        WHEN 'geom' THEN 'PostGIS geometry in the current GeoFlow development storage SRID.'
        ELSE NULL
    END AS description
FROM gis.meta_feature_type ft
JOIN information_schema.columns c
  ON c.table_schema = 'gis'
 AND c.table_name = ft.physical_name
WHERE ft.domain_code IN ('WTL','SWL')
ON CONFLICT (feature_type_id, physical_name) DO UPDATE SET
    standard_name = EXCLUDED.standard_name,
    label = EXCLUDED.label,
    data_type = EXCLUDED.data_type,
    unit = EXCLUDED.unit,
    code_group_key = EXCLUDED.code_group_key,
    widget_type = EXCLUDED.widget_type,
    required_default = EXCLUDED.required_default,
    core_field = EXCLUDED.core_field,
    sort_order = EXCLUDED.sort_order,
    description = EXCLUDED.description;

-- Default pilot profile for the initial WTL/SWL feature set.
INSERT INTO gis.profile (id, code, name, municipality, version, active, description)
VALUES (
    '0f4b7a6f-7e72-4b70-b62d-8b66ee878001'::uuid,
    'GEOFLOW_DEV_WTL_SWL',
    'GeoFlow 개발 상수·하수 기본 Profile',
    NULL,
    '0.1',
    true,
    'Initial development profile for the 9 WTL + 8 SWL physical feature tables.'
)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    version = EXCLUDED.version,
    active = EXCLUDED.active,
    description = EXCLUDED.description,
    updated_at = now();

INSERT INTO gis.profile_feature (id, profile_id, feature_type_id, enabled, required, sort_order)
SELECT
    md5('profile-feature:' || ft.id::text)::uuid,
    '0f4b7a6f-7e72-4b70-b62d-8b66ee878001'::uuid,
    ft.id,
    true,
    false,
    ft.sort_order
FROM gis.meta_feature_type ft
WHERE ft.domain_code IN ('WTL','SWL')
ON CONFLICT (profile_id, feature_type_id) DO UPDATE SET
    enabled = true,
    sort_order = EXCLUDED.sort_order;

INSERT INTO gis.profile_field (id, profile_id, field_def_id, enabled, required, editable, visible, sort_order)
SELECT
    md5('profile-field:' || fd.id::text)::uuid,
    '0f4b7a6f-7e72-4b70-b62d-8b66ee878001'::uuid,
    fd.id,
    CASE WHEN fd.physical_name IN ('gid','source_name','source_key','created_at','updated_at','created_by','updated_by','ext_data') THEN false ELSE true END,
    CASE WHEN fd.physical_name IN ('id') THEN true ELSE false END,
    CASE WHEN fd.physical_name IN ('id','created_at','updated_at','created_by','updated_by') THEN false ELSE true END,
    CASE WHEN fd.physical_name IN ('gid','ext_data','source_name','source_key','created_at','updated_at','created_by','updated_by') THEN false ELSE true END,
    fd.sort_order
FROM gis.meta_field_def fd
JOIN gis.meta_feature_type ft ON ft.id = fd.feature_type_id
WHERE ft.domain_code IN ('WTL','SWL')
ON CONFLICT (profile_id, field_def_id) DO UPDATE SET
    enabled = EXCLUDED.enabled,
    required = EXCLUDED.required,
    editable = EXCLUDED.editable,
    visible = EXCLUDED.visible,
    sort_order = EXCLUDED.sort_order;

COMMIT;

SELECT ft.domain_code, count(*) AS field_count
FROM gis.meta_field_def fd
JOIN gis.meta_feature_type ft ON ft.id = fd.feature_type_id
WHERE ft.domain_code IN ('WTL','SWL')
GROUP BY ft.domain_code
ORDER BY ft.domain_code;

SELECT p.code, count(pf.feature_type_id) AS feature_count
FROM gis.profile p
JOIN gis.profile_feature pf ON pf.profile_id = p.id
WHERE p.code = 'GEOFLOW_DEV_WTL_SWL'
GROUP BY p.code;
