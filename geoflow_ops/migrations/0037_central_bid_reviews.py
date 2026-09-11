from django.db import migrations

SQL = """
CREATE TABLE IF NOT EXISTS bid.central_reviews (
    central_notice_id uuid PRIMARY KEY,
    legacy_notice_id uuid UNIQUE NULL,
    notice_number varchar(80) NOT NULL,
    notice_order varchar(20) NOT NULL,
    title text NOT NULL,
    detail_url text NULL,
    status varchar(30) NOT NULL DEFAULT 'unreviewed'
      CHECK(status IN ('unreviewed','reviewing','interested','considering','excluded')),
    memo text NOT NULL DEFAULT '',
    updated_by varchar(255) NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bid_central_review_status_idx ON bid.central_reviews(status, central_notice_id);
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0036_bid_interest_foundation")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
