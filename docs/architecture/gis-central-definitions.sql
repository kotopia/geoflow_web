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
