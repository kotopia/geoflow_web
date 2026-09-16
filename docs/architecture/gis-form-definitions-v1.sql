-- Reviewed additive proposal. Do not execute on production before explicit schema approval.
-- Apply inside one transaction after verifying the existing GIS/profile/project foundation.
-- No existing facility, reference value, or profile row is rewritten.
CREATE TABLE gis.form_item (
    id uuid PRIMARY KEY,
    feature_type_id uuid NOT NULL REFERENCES gis.meta_feature_type(id),
    label text NOT NULL CHECK (length(btrim(label)) BETWEEN 1 AND 120),
    kind text NOT NULL CHECK (kind IN ('scalar','photo','survey_relation')),
    config jsonb NOT NULL CHECK (jsonb_typeof(config)='object'),
    code_group_key text REFERENCES gis.ref_code_group(group_key),
    origin_project_id uuid REFERENCES prj.projects(id),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE gis.profile_form_item (
    profile_id uuid NOT NULL REFERENCES gis.profile(id),
    item_id uuid NOT NULL REFERENCES gis.form_item(id),
    enabled boolean NOT NULL DEFAULT true,
    required_on_complete boolean NOT NULL DEFAULT false,
    PRIMARY KEY (profile_id,item_id)
);
CREATE TABLE gis.project_form_item (
    project_id uuid NOT NULL REFERENCES prj.projects(id),
    item_id uuid NOT NULL REFERENCES gis.form_item(id),
    enabled boolean NOT NULL DEFAULT true,
    PRIMARY KEY (project_id,item_id)
);
CREATE INDEX form_item_feature_idx ON gis.form_item(feature_type_id);
CREATE INDEX form_item_origin_idx ON gis.form_item(origin_project_id);
CREATE INDEX profile_form_item_item_idx ON gis.profile_form_item(item_id);
CREATE INDEX project_form_item_item_idx ON gis.project_form_item(item_id);
