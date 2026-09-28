-- Existing central catalogue transition. Pre-service photo catalogue test rows are reset.
-- Production execution requires a read-only inventory and separate approval.
CREATE TABLE IF NOT EXISTS gis.photo_variant (
 id uuid PRIMARY KEY, template_id uuid NOT NULL REFERENCES gis.photo_template(id),
 code text NOT NULL CHECK(code ~ '^[A-Z][A-Z0-9_]*$'), name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
 description text NOT NULL DEFAULT '', active boolean NOT NULL DEFAULT true, sort_order integer NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(template_id,code)
);
CREATE TABLE IF NOT EXISTS gis.photo_policy_template (
 id uuid PRIMARY KEY, policy_id uuid NOT NULL REFERENCES gis.photo_policy(id),
 template_id uuid NOT NULL REFERENCES gis.photo_template(id), sort_order integer NOT NULL DEFAULT 0,
 active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(policy_id,template_id)
);
DELETE FROM gis.photo_policy_template;
DELETE FROM gis.photo_policy;
DELETE FROM gis.photo_slot;
DELETE FROM gis.photo_variant;
DELETE FROM gis.photo_template;
ALTER TABLE gis.photo_template DROP COLUMN IF EXISTS capture_mode;
ALTER TABLE gis.photo_slot ADD COLUMN IF NOT EXISTS variant_id uuid;
ALTER TABLE gis.photo_slot DROP CONSTRAINT IF EXISTS photo_slot_template_id_fkey;
ALTER TABLE gis.photo_slot DROP CONSTRAINT IF EXISTS photo_slot_template_id_code_key;
ALTER TABLE gis.photo_slot DROP COLUMN IF EXISTS template_id;
ALTER TABLE gis.photo_slot ALTER COLUMN variant_id SET NOT NULL;
ALTER TABLE gis.photo_slot DROP CONSTRAINT IF EXISTS photo_slot_variant_id_fkey;
ALTER TABLE gis.photo_slot DROP CONSTRAINT IF EXISTS photo_slot_variant_code_uq;
ALTER TABLE gis.photo_slot ADD CONSTRAINT photo_slot_variant_id_fkey FOREIGN KEY(variant_id) REFERENCES gis.photo_variant(id);
ALTER TABLE gis.photo_slot ADD CONSTRAINT photo_slot_variant_code_uq UNIQUE(variant_id,code);
ALTER TABLE gis.photo_policy DROP CONSTRAINT IF EXISTS photo_policy_check;
ALTER TABLE gis.photo_policy DROP CONSTRAINT IF EXISTS photo_policy_default_capture_mode_check;
ALTER TABLE gis.photo_policy DROP COLUMN IF EXISTS default_capture_mode;
ALTER TABLE gis.photo_policy DROP COLUMN IF EXISTS direct_template_id;
ALTER TABLE gis.photo_policy DROP COLUMN IF EXISTS indirect_template_id;
ALTER TABLE gis.photo_policy DROP COLUMN IF EXISTS general_template_id;
ALTER TABLE gis.photo_policy DROP COLUMN IF EXISTS allow_extra_photo;
DROP INDEX IF EXISTS gis.photo_slot_template_order_idx;
CREATE INDEX IF NOT EXISTS photo_variant_template_order_idx ON gis.photo_variant(template_id,sort_order) WHERE active;
CREATE INDEX IF NOT EXISTS photo_slot_variant_order_idx ON gis.photo_slot(variant_id,sort_order) WHERE active;
CREATE INDEX IF NOT EXISTS photo_policy_template_order_idx ON gis.photo_policy_template(policy_id,sort_order) WHERE active;
