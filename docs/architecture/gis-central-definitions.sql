-- GeoFlow central GIS definitions v3.
-- The default database is the only authoring source. Tenant databases keep
-- project selection and physical feature rows, never copies of these rules.
CREATE SCHEMA IF NOT EXISTS gis;

CREATE TABLE gis.definition_group (
 id uuid PRIMARY KEY, name text NOT NULL UNIQUE CHECK(length(btrim(name)) BETWEEN 1 AND 120)
);
CREATE TABLE gis.definition_layer (
 id uuid PRIMARY KEY,
 standard_name text NOT NULL UNIQUE CHECK(length(btrim(standard_name)) BETWEEN 1 AND 120),
 physical_name text NOT NULL UNIQUE CHECK(physical_name ~ '^[a-z_][a-z0-9_]*$'),
 label text NOT NULL CHECK(length(btrim(label)) BETWEEN 1 AND 120),
 domain_code text NOT NULL DEFAULT '',
 geometry_kind text NOT NULL DEFAULT '' CHECK(geometry_kind IN ('','POINT','LINE','POLYGON')),
 feature_role text NOT NULL DEFAULT 'ASSET',
 scope_type text NOT NULL DEFAULT 'PROJECT',
 sort_order integer NOT NULL DEFAULT 0,
 active boolean NOT NULL DEFAULT true
);
-- L2 is catalog.category_node. L3/L4 are catalog facet options. A single FK
-- cannot target both kinds, so application validation verifies catalog_item_id.
CREATE TABLE gis.definition_layer_catalog (
 layer_id uuid NOT NULL REFERENCES gis.definition_layer(id),
 catalog_level smallint NOT NULL CHECK(catalog_level BETWEEN 2 AND 4),
 catalog_item_id uuid NOT NULL,
 sort_order integer NOT NULL DEFAULT 0,
 PRIMARY KEY(layer_id,catalog_level,catalog_item_id)
);
CREATE TABLE gis.definition_field (
 id uuid PRIMARY KEY,
 source_layer_id uuid REFERENCES gis.definition_layer(id),
 physical_name text,
 standard_name text,
 label text NOT NULL CHECK(length(btrim(label)) BETWEEN 1 AND 120),
 storage_data_type text,
 storage_udt_name text,
 max_length integer CHECK(max_length BETWEEN 1 AND 1000000),
 precision integer CHECK(precision BETWEEN 1 AND 1000),
 scale integer CHECK(scale BETWEEN 0 AND 1000),
 nullable boolean NOT NULL DEFAULT true,
 storage_default text,
 kind text NOT NULL CHECK(kind IN ('text','integer','decimal','boolean','date','datetime','photo','relation')),
 widget_type text NOT NULL DEFAULT 'text' CHECK(widget_type IN
  ('text','multiline','integer','decimal','combo','boolean','date','datetime','photo','relation','hidden')),
 visible boolean NOT NULL DEFAULT true,
 required boolean NOT NULL DEFAULT false,
 readonly boolean NOT NULL DEFAULT false,
 default_value jsonb,
 sort_order integer NOT NULL DEFAULT 0,
 unit text NOT NULL DEFAULT '',
 description text NOT NULL DEFAULT '',
 layout jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(layout)='object'),
 CHECK((source_layer_id IS NULL) = (physical_name IS NULL)),
 CHECK((precision IS NULL AND scale IS NULL) OR
       (precision IS NOT NULL AND scale IS NOT NULL AND scale<=precision)),
 UNIQUE(source_layer_id,physical_name)
);
CREATE TABLE gis.definition_field_layer (
 field_id uuid NOT NULL REFERENCES gis.definition_field(id),
 layer_id uuid NOT NULL REFERENCES gis.definition_layer(id),
 PRIMARY KEY(field_id,layer_id)
);
CREATE TABLE gis.definition_code (
 id uuid PRIMARY KEY,
 field_id uuid NOT NULL REFERENCES gis.definition_field(id),
 code text NOT NULL CHECK(length(btrim(code)) BETWEEN 1 AND 120),
 label text NOT NULL CHECK(length(btrim(label)) BETWEEN 1 AND 120),
 sort_order integer NOT NULL DEFAULT 0,
 enabled boolean NOT NULL DEFAULT true,
 UNIQUE(field_id,code), UNIQUE(id,field_id)
);
CREATE TABLE gis.definition_group_scope (
 group_id uuid NOT NULL REFERENCES gis.definition_group(id),
 catalog_level smallint NOT NULL CHECK(catalog_level BETWEEN 2 AND 4),
 catalog_item_id uuid NOT NULL,
 PRIMARY KEY(group_id,catalog_level,catalog_item_id)
);
CREATE TABLE gis.definition_group_layer (
 group_id uuid NOT NULL REFERENCES gis.definition_group(id),
 layer_id uuid NOT NULL REFERENCES gis.definition_layer(id),
 PRIMARY KEY(group_id,layer_id)
);
CREATE TABLE gis.definition_group_field (
 group_id uuid NOT NULL,
 layer_id uuid NOT NULL,
 field_id uuid NOT NULL REFERENCES gis.definition_field(id),
 sort_order integer NOT NULL DEFAULT 0,
 required boolean NOT NULL DEFAULT false,
 visible boolean,
 readonly boolean,
 layout jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(layout)='object'),
 PRIMARY KEY(group_id,layer_id,field_id),
 FOREIGN KEY(group_id,layer_id) REFERENCES gis.definition_group_layer(group_id,layer_id)
);
CREATE TABLE gis.definition_rule (
 id uuid PRIMARY KEY,
 source_field uuid NOT NULL REFERENCES gis.definition_field(id),
 source_code uuid NOT NULL,
 target_field uuid NOT NULL REFERENCES gis.definition_field(id),
 CHECK(source_field<>target_field), UNIQUE(source_field,source_code,target_field), UNIQUE(id,target_field),
 FOREIGN KEY(source_code,source_field) REFERENCES gis.definition_code(id,field_id)
);
CREATE TABLE gis.definition_rule_value (
 rule_id uuid NOT NULL,
 target_field uuid NOT NULL,
 code_id uuid NOT NULL,
 PRIMARY KEY(rule_id,code_id),
 FOREIGN KEY(rule_id,target_field) REFERENCES gis.definition_rule(id,target_field),
 FOREIGN KEY(code_id,target_field) REFERENCES gis.definition_code(id,field_id)
);
COMMENT ON TABLE gis.definition_group IS 'GeoFlow central GIS definitions v3; no tenant operational records';

-- Central GIS definition administration extension (v4-compatible, additive only).
-- definition_group remains the existing business/form inheritance group.
-- Layer taxonomy (water/sewer/road/etc.) is intentionally separate.
CREATE TABLE IF NOT EXISTS gis.definition_layer_group (
 id uuid PRIMARY KEY,
 group_code text NOT NULL UNIQUE CHECK(group_code ~ '^[a-z_][a-z0-9_]*$'),
 group_name text NOT NULL CHECK(length(btrim(group_name)) BETWEEN 1 AND 120),
 display_name text NOT NULL CHECK(length(btrim(display_name)) BETWEEN 1 AND 120),
 sort_order integer NOT NULL DEFAULT 0,
 active boolean NOT NULL DEFAULT true,
 description text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE gis.definition_layer
  ADD COLUMN IF NOT EXISTS layer_group_id uuid REFERENCES gis.definition_layer_group(id),
  ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS definition_layer_layer_group_idx
  ON gis.definition_layer(layer_group_id,sort_order,standard_name);

ALTER TABLE gis.definition_field
  ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS form_visible boolean,
  ADD COLUMN IF NOT EXISTS table_visible boolean,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS gis.definition_change_log (
 id uuid PRIMARY KEY,
 actor text NOT NULL DEFAULT '',
 target_type text NOT NULL CHECK(target_type IN ('GROUP','LAYER','FIELD','SCHEMA')),
 target_id uuid,
 change_type text NOT NULL,
 before_value jsonb,
 after_value jsonb,
 schema_applied boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS definition_change_log_target_idx
  ON gis.definition_change_log(target_type,target_id,created_at DESC);

CREATE TABLE IF NOT EXISTS gis.schema_change (
 id uuid PRIMARY KEY,
 operation text NOT NULL CHECK(operation IN
   ('ADD_COLUMN','RENAME_COLUMN','DEPRECATE','DROP_COLUMN','ALTER_TYPE')),
 layer_id uuid NOT NULL REFERENCES gis.definition_layer(id),
 field_id uuid REFERENCES gis.definition_field(id),
 old_name text,
 new_name text,
 old_type text,
 new_type text,
 status text NOT NULL DEFAULT 'PENDING' CHECK(status IN
   ('PENDING','APPROVED','APPLYING','APPLIED','PARTIAL_APPLIED','PARTIAL_FAILED','FAILED','CANCELLED')),
 preview_sql text NOT NULL DEFAULT '',
 impact jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(impact)='object'),
 created_by text NOT NULL DEFAULT '',
 approved_by text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(),
 approved_at timestamptz
);

CREATE TABLE IF NOT EXISTS gis.schema_change_tenant (
 change_id uuid NOT NULL REFERENCES gis.schema_change(id) ON DELETE CASCADE,
 tenant_group_id uuid NOT NULL,
 status text NOT NULL DEFAULT 'PENDING' CHECK(status IN
   ('PENDING','APPROVED','APPLYING','APPLIED','PARTIAL_APPLIED','PARTIAL_FAILED','FAILED','CANCELLED')),
 error_message text NOT NULL DEFAULT '',
 applied_at timestamptz,
 before_schema jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(before_schema)='object'),
 after_schema jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(after_schema)='object'),
 PRIMARY KEY(change_id,tenant_group_id)
);
