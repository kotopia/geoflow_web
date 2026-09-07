\encoding UTF8
-- GeoFlow GIS project-scope capability layer v0.1
-- DEVELOPMENT / PILOT ONLY.
-- Additive metadata linking prj.scope_item business scope to GIS layer plans.

BEGIN;

DO $$
BEGIN
    IF current_database() !~* '(dev|test)' THEN
        RAISE EXCEPTION 'Safety stop: GIS scope capability DDL may run only in dev/test DB. Current DB=%', current_database();
    END IF;
    IF to_regclass('prj.projects') IS NULL OR to_regclass('prj.scope_item') IS NULL THEN
        RAISE EXCEPTION 'Project/scope foundation is missing.';
    END IF;
    IF to_regclass('gis.meta_feature_type') IS NULL OR to_regclass('gis.profile') IS NULL THEN
        RAISE EXCEPTION 'GIS metadata/profile foundation is missing.';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS gis.capability (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gis.capability_feature (
    id uuid PRIMARY KEY,
    capability_id uuid NOT NULL REFERENCES gis.capability(id) ON DELETE CASCADE,
    feature_type_id uuid NOT NULL REFERENCES gis.meta_feature_type(id) ON DELETE CASCADE,
    enabled boolean NOT NULL DEFAULT true,
    required boolean NOT NULL DEFAULT false,
    sort_order integer NOT NULL DEFAULT 0,
    UNIQUE(capability_id, feature_type_id)
);

-- catalog_item_id references a central catalog UUID semantically. No cross-DB FK
-- is created because catalog and tenant DBs are intentionally separate.
CREATE TABLE IF NOT EXISTS gis.scope_binding (
    id uuid PRIMARY KEY,
    catalog_level smallint NOT NULL CHECK (catalog_level IN (2,3,4)),
    catalog_item_id uuid NOT NULL,
    catalog_code_cache text,
    catalog_name_cache text,
    capability_id uuid NOT NULL REFERENCES gis.capability(id) ON DELETE CASCADE,
    active boolean NOT NULL DEFAULT true,
    priority integer NOT NULL DEFAULT 0,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(catalog_level, catalog_item_id, capability_id)
);
CREATE INDEX IF NOT EXISTS scope_binding_lookup_idx
    ON gis.scope_binding(catalog_level, catalog_item_id) WHERE active;

CREATE TABLE IF NOT EXISTS gis.project_profile (
    project_id uuid PRIMARY KEY REFERENCES prj.projects(id) ON DELETE CASCADE,
    profile_id uuid NOT NULL REFERENCES gis.profile(id),
    status text NOT NULL DEFAULT 'active',
    auto_assigned boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS project_profile_profile_idx ON gis.project_profile(profile_id);

-- Stable capability identities for the first GeoFlow underground-infrastructure scope.
INSERT INTO gis.capability(id, code, name, active, sort_order, description)
VALUES
 ('80000000-0000-4000-8000-000000000001'::uuid,'WATER','상수도 GIS',true,10,'Water utility GIS capability; initial WTL feature family.'),
 ('80000000-0000-4000-8000-000000000002'::uuid,'SEWER','하수도 GIS',true,20,'Sewer GIS capability; initial SWL feature family.'),
 ('80000000-0000-4000-8000-000000000003'::uuid,'ROAD','도로 GIS',true,30,'Road GIS capability. Initial pilot exposes the common road reference only; road asset feature families are additive later.'),
 ('80000000-0000-4000-8000-000000000004'::uuid,'SURVEY','측량 GIS',true,40,'Common field-survey capability.')
ON CONFLICT (code) DO UPDATE SET
    name=EXCLUDED.name,
    active=true,
    sort_order=EXCLUDED.sort_order,
    description=EXCLUDED.description,
    updated_at=now();

-- Capability -> feature is metadata, not application hardcoding. Common survey/
-- road-reference layers are explicitly included where they are useful.
INSERT INTO gis.capability_feature(id, capability_id, feature_type_id, enabled, required, sort_order)
SELECT gen_random_uuid(), c.id, ft.id, true,
       CASE WHEN ft.standard_name='SURVEY' THEN true ELSE false END,
       ft.sort_order
FROM gis.capability c
JOIN gis.meta_feature_type ft ON ft.active
WHERE
    (c.code='WATER' AND ft.domain_code IN ('COMMON','WTL')) OR
    (c.code='SEWER' AND ft.domain_code IN ('COMMON','SWL')) OR
    (c.code='SURVEY' AND ft.standard_name IN ('SURVEY','DORO')) OR
    (c.code='ROAD' AND ft.standard_name='DORO')
ON CONFLICT (capability_id, feature_type_id) DO UPDATE SET
    enabled=true,
    required=EXCLUDED.required,
    sort_order=EXCLUDED.sort_order;

COMMIT;
