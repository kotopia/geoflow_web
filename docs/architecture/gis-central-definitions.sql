-- Central default DB only; execute transactionally via deploy_gis_central_definitions.
CREATE SCHEMA IF NOT EXISTS gis;
CREATE TABLE gis.definition_group (
 id uuid PRIMARY KEY, name text NOT NULL UNIQUE CHECK(length(btrim(name)) BETWEEN 1 AND 120)
);
CREATE TABLE gis.definition_layer (
 standard_name text PRIMARY KEY, label text NOT NULL
);
CREATE TABLE gis.definition_layer_catalog (
 layer_name text REFERENCES gis.definition_layer(standard_name),
 catalog_id uuid REFERENCES catalog.category_node(id), PRIMARY KEY(layer_name,catalog_id)
);
CREATE TABLE gis.definition_field (
 id uuid PRIMARY KEY, label text NOT NULL CHECK(length(btrim(label)) BETWEEN 1 AND 120),
 kind text NOT NULL CHECK(kind IN ('text','integer','decimal','boolean','date','photo','relation')),
 max_length integer CHECK(max_length BETWEEN 1 AND 100000),
 precision integer CHECK(precision BETWEEN 1 AND 38), scale integer CHECK(scale BETWEEN 0 AND 38),
 sort_order integer NOT NULL DEFAULT 0,
 source_layer text REFERENCES gis.definition_layer(standard_name), physical_name text,
 CHECK((source_layer IS NULL) = (physical_name IS NULL)),
 CHECK((precision IS NULL AND scale IS NULL) OR (precision IS NOT NULL AND scale IS NOT NULL AND scale<=precision)),
 UNIQUE(source_layer,physical_name)
);
CREATE TABLE gis.definition_field_layer (
 field_id uuid REFERENCES gis.definition_field(id), layer_name text REFERENCES gis.definition_layer(standard_name),
 PRIMARY KEY(field_id,layer_name)
);
CREATE TABLE gis.definition_code (
 id uuid PRIMARY KEY, field_id uuid NOT NULL REFERENCES gis.definition_field(id),
 code text NOT NULL CHECK(length(btrim(code)) BETWEEN 1 AND 120),
 label text NOT NULL CHECK(length(btrim(label)) BETWEEN 1 AND 120), sort_order integer NOT NULL DEFAULT 0,
 UNIQUE(field_id,code), UNIQUE(id,field_id)
);
CREATE TABLE gis.definition_group_scope (
 group_id uuid REFERENCES gis.definition_group(id), catalog_id uuid REFERENCES catalog.category_node(id),
 PRIMARY KEY(group_id,catalog_id)
);
CREATE TABLE gis.definition_group_layer (
 group_id uuid REFERENCES gis.definition_group(id), layer_name text REFERENCES gis.definition_layer(standard_name),
 PRIMARY KEY(group_id,layer_name)
);
CREATE TABLE gis.definition_group_field (
 group_id uuid NOT NULL, layer_name text NOT NULL, field_id uuid REFERENCES gis.definition_field(id),
 sort_order integer NOT NULL DEFAULT 0, required boolean NOT NULL DEFAULT false,
 PRIMARY KEY(group_id,layer_name,field_id),
 FOREIGN KEY(group_id,layer_name) REFERENCES gis.definition_group_layer(group_id,layer_name)
);
CREATE TABLE gis.definition_rule (
 id uuid PRIMARY KEY, source_field uuid NOT NULL REFERENCES gis.definition_field(id),
 source_code uuid NOT NULL, target_field uuid NOT NULL REFERENCES gis.definition_field(id),
 CHECK(source_field<>target_field), UNIQUE(source_field,source_code,target_field), UNIQUE(id,target_field),
 FOREIGN KEY(source_code,source_field) REFERENCES gis.definition_code(id,field_id)
);
CREATE TABLE gis.definition_rule_value (
 rule_id uuid NOT NULL, target_field uuid NOT NULL, code_id uuid NOT NULL,
 PRIMARY KEY(rule_id,code_id),
 FOREIGN KEY(rule_id,target_field) REFERENCES gis.definition_rule(id,target_field),
 FOREIGN KEY(code_id,target_field) REFERENCES gis.definition_code(id,field_id)
);
COMMENT ON TABLE gis.definition_group IS 'GeoFlow central GIS definitions v2; no tenant operational records';
