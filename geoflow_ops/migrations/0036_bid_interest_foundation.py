from django.db import migrations


FORWARD_SQL = r"""
CREATE SCHEMA IF NOT EXISTS bid;

CREATE TABLE IF NOT EXISTS bid.filter_values (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind varchar(20) NOT NULL CHECK (kind IN ('region','industry','agency')),
    code varchar(120) NOT NULL,
    name varchar(255) NOT NULL,
    aliases text[] NOT NULL DEFAULT '{}',
    active boolean NOT NULL DEFAULT true,
    ord integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(kind, code)
);
CREATE INDEX IF NOT EXISTS idx_bid_filter_value_active
    ON bid.filter_values(kind, active, ord, name);

CREATE TABLE IF NOT EXISTS bid.keyword_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_type varchar(20) NOT NULL CHECK (rule_type IN ('include','exclude')),
    keyword varchar(200) NOT NULL,
    active boolean NOT NULL DEFAULT true,
    ord integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(rule_type, keyword)
);

CREATE TABLE IF NOT EXISTS bid.notices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source varchar(30) NOT NULL DEFAULT 'g2b',
    bid_notice_no varchar(80) NOT NULL,
    bid_notice_ord varchar(20) NOT NULL DEFAULT '00',
    business_type varchar(30) NOT NULL DEFAULT 'service',
    title text NOT NULL,
    notice_kind varchar(120) NULL,
    notice_agency_code varchar(120) NULL,
    notice_agency_name varchar(255) NULL,
    demand_agency_code varchar(120) NULL,
    demand_agency_name varchar(255) NULL,
    bid_method_name varchar(255) NULL,
    contract_method_name varchar(255) NULL,
    region_text text NULL,
    industry_text text NULL,
    region_items jsonb NOT NULL DEFAULT '[]'::jsonb,
    industry_items jsonb NOT NULL DEFAULT '[]'::jsonb,
    posted_at timestamptz NULL,
    bid_begin_at timestamptz NULL,
    bid_close_at timestamptz NULL,
    open_at timestamptz NULL,
    basic_amount numeric(20,0) NULL,
    estimated_price numeric(20,0) NULL,
    budget_amount numeric(20,0) NULL,
    detail_url text NULL,
    notice_status varchar(40) NOT NULL DEFAULT 'open',
    is_correction boolean NOT NULL DEFAULT false,
    payload_hash varchar(64) NOT NULL,
    raw_payload jsonb NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    source_updated_at timestamptz NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(source, bid_notice_no, bid_notice_ord)
);
CREATE INDEX IF NOT EXISTS idx_bid_notice_posted ON bid.notices(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_bid_notice_close ON bid.notices(bid_close_at);
CREATE INDEX IF NOT EXISTS idx_bid_notice_status ON bid.notices(notice_status, bid_close_at);

CREATE TABLE IF NOT EXISTS bid.notice_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    notice_id uuid NOT NULL REFERENCES bid.notices(id) ON DELETE CASCADE,
    payload_hash varchar(64) NOT NULL,
    raw_payload jsonb NOT NULL,
    captured_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(notice_id, payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_bid_notice_revision
    ON bid.notice_revisions(notice_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS bid.notice_matches (
    notice_id uuid PRIMARY KEY REFERENCES bid.notices(id) ON DELETE CASCADE,
    matched boolean NOT NULL DEFAULT false,
    needs_review boolean NOT NULL DEFAULT false,
    reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    evaluated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bid_notice_match_result
    ON bid.notice_matches(matched, needs_review, evaluated_at DESC);

CREATE TABLE IF NOT EXISTS bid.notice_reviews (
    notice_id uuid PRIMARY KEY REFERENCES bid.notices(id) ON DELETE CASCADE,
    status varchar(30) NOT NULL DEFAULT 'unreviewed'
        CHECK (status IN ('unreviewed','reviewing','interested','considering','excluded')),
    memo text NULL,
    updated_by varchar(255) NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bid.sync_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    operation varchar(100) NOT NULL,
    status varchar(20) NOT NULL CHECK (status IN ('running','success','partial','failed')),
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    fetched_count integer NOT NULL DEFAULT 0,
    inserted_count integer NOT NULL DEFAULT 0,
    updated_count integer NOT NULL DEFAULT 0,
    matched_count integer NOT NULL DEFAULT 0,
    error_code varchar(100) NULL,
    error_message text NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz NULL
);
CREATE INDEX IF NOT EXISTS idx_bid_sync_started ON bid.sync_runs(started_at DESC);

INSERT INTO bid.filter_values(kind, code, name, aliases, active, ord)
VALUES
 ('region','11','서울특별시',ARRAY['서울'],false,10),
 ('region','26','부산광역시',ARRAY['부산'],false,20),
 ('region','27','대구광역시',ARRAY['대구'],false,30),
 ('region','28','인천광역시',ARRAY['인천'],false,40),
 ('region','29','광주광역시',ARRAY['광주'],false,50),
 ('region','30','대전광역시',ARRAY['대전'],false,60),
 ('region','31','울산광역시',ARRAY['울산'],false,70),
 ('region','36','세종특별자치시',ARRAY['세종'],false,80),
 ('region','41','경기도',ARRAY['경기'],false,90),
 ('region','51','강원특별자치도',ARRAY['강원도','강원'],false,100),
 ('region','43','충청북도',ARRAY['충북'],false,110),
 ('region','44','충청남도',ARRAY['충남'],false,120),
 ('region','52','전북특별자치도',ARRAY['전라북도','전북'],false,130),
 ('region','46','전라남도',ARRAY['전남'],false,140),
 ('region','47','경상북도',ARRAY['경북'],false,150),
 ('region','48','경상남도',ARRAY['경남'],false,160),
 ('region','50','제주특별자치도',ARRAY['제주도','제주'],false,170)
ON CONFLICT (kind, code) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0035_employee_education_career_settings")]
    operations = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
