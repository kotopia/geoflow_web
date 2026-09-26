-- Central-only GIS photo policy definitions. Apply separately after the
-- central GIS definition schema; never as an incidental tenant migration.
CREATE TABLE IF NOT EXISTS gis.photo_template (
 id uuid PRIMARY KEY,
 code text NOT NULL UNIQUE CHECK(code ~ '^[A-Z][A-Z0-9_]*$'),
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
 description text NOT NULL DEFAULT '',
 capture_mode text NOT NULL CHECK(capture_mode IN ('DIRECT','INDIRECT','GENERAL')),
 active boolean NOT NULL DEFAULT true,
 sort_order integer NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gis.photo_slot (
 id uuid PRIMARY KEY,
 template_id uuid NOT NULL REFERENCES gis.photo_template(id),
 code text NOT NULL CHECK(code ~ '^[A-Z][A-Z0-9_]*$'),
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
 description text NOT NULL DEFAULT '',
 min_count integer NOT NULL DEFAULT 1 CHECK(min_count >= 0),
 max_count integer NOT NULL DEFAULT 1 CHECK(max_count >= min_count),
 sort_order integer NOT NULL DEFAULT 0,
 active boolean NOT NULL DEFAULT true,
 extra_schema jsonb NOT NULL DEFAULT '{"fields":[]}'::jsonb CHECK(jsonb_typeof(extra_schema)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(template_id,code)
);

CREATE TABLE IF NOT EXISTS gis.photo_policy (
 id uuid PRIMARY KEY,
 lv2_id uuid NOT NULL REFERENCES catalog.category_node(id),
 lv3_id uuid REFERENCES catalog.category_facet_option(id),
 layer_id uuid NOT NULL REFERENCES gis.definition_layer(id),
 default_capture_mode text NOT NULL DEFAULT 'DIRECT'
   CHECK(default_capture_mode IN ('DIRECT','INDIRECT','GENERAL')),
 direct_template_id uuid REFERENCES gis.photo_template(id),
 indirect_template_id uuid REFERENCES gis.photo_template(id),
 general_template_id uuid REFERENCES gis.photo_template(id),
 allow_extra_photo boolean NOT NULL DEFAULT true,
 active boolean NOT NULL DEFAULT true,
 sort_order integer NOT NULL DEFAULT 0,
 description text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(direct_template_id IS NOT NULL OR indirect_template_id IS NOT NULL OR general_template_id IS NOT NULL)
);
ALTER TABLE gis.photo_policy ADD COLUMN IF NOT EXISTS general_template_id uuid
 REFERENCES gis.photo_template(id);
ALTER TABLE gis.photo_policy DROP CONSTRAINT IF EXISTS photo_policy_default_capture_mode_check;
ALTER TABLE gis.photo_policy ADD CONSTRAINT photo_policy_default_capture_mode_check
 CHECK(default_capture_mode IN ('DIRECT','INDIRECT','GENERAL'));
ALTER TABLE gis.photo_policy DROP CONSTRAINT IF EXISTS photo_policy_check;
ALTER TABLE gis.photo_policy ADD CONSTRAINT photo_policy_check
 CHECK(direct_template_id IS NOT NULL OR indirect_template_id IS NOT NULL OR general_template_id IS NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS photo_policy_l2_default_uq
 ON gis.photo_policy(lv2_id,layer_id) WHERE lv3_id IS NULL AND active;
CREATE UNIQUE INDEX IF NOT EXISTS photo_policy_l3_uq
 ON gis.photo_policy(lv2_id,lv3_id,layer_id) WHERE lv3_id IS NOT NULL AND active;
CREATE INDEX IF NOT EXISTS photo_policy_layer_idx ON gis.photo_policy(layer_id,active);
CREATE INDEX IF NOT EXISTS photo_slot_template_order_idx
 ON gis.photo_slot(template_id,sort_order);
