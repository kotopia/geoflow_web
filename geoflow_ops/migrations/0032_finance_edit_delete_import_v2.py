from django.db import migrations


FORWARD_SQL = r"""
-- Finance v2: editable records, reversible user deletion, import provenance.
-- Existing Finance rows were explicitly approved as disposable test data for this rollout.

ALTER TABLE fin.claims
    ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS deleted_by varchar(255) NULL;

ALTER TABLE fin.payment_requests
    ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS deleted_by varchar(255) NULL;

ALTER TABLE fin.tax_invoices
    ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS deleted_by varchar(255) NULL,
    ADD COLUMN IF NOT EXISTS source_type varchar(40) NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS source_partner_name varchar(255) NULL,
    ADD COLUMN IF NOT EXISTS source_partner_biz_no varchar(40) NULL,
    ADD COLUMN IF NOT EXISTS import_fingerprint varchar(64) NULL,
    ADD COLUMN IF NOT EXISTS import_batch_id uuid NULL;

ALTER TABLE fin.transactions
    ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS deleted_by varchar(255) NULL,
    ADD COLUMN IF NOT EXISTS source_type varchar(40) NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS source_partner_name varchar(255) NULL,
    ADD COLUMN IF NOT EXISTS source_partner_biz_no varchar(40) NULL,
    ADD COLUMN IF NOT EXISTS import_fingerprint varchar(64) NULL,
    ADD COLUMN IF NOT EXISTS import_batch_id uuid NULL;

CREATE INDEX IF NOT EXISTS idx_fin_claim_deleted ON fin.claims(is_deleted, claim_date DESC);
CREATE INDEX IF NOT EXISTS idx_fin_payreq_deleted ON fin.payment_requests(is_deleted, request_date DESC);
CREATE INDEX IF NOT EXISTS idx_fin_invoice_deleted ON fin.tax_invoices(is_deleted, written_date DESC);
CREATE INDEX IF NOT EXISTS idx_fin_invoice_fingerprint ON fin.tax_invoices(import_fingerprint) WHERE import_fingerprint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fin_tx_deleted ON fin.transactions(is_deleted, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_fin_tx_fingerprint ON fin.transactions(import_fingerprint) WHERE import_fingerprint IS NOT NULL;

-- Clear only the transactional Finance rows created during the initial test period.
-- Account master data is intentionally preserved.
TRUNCATE TABLE
    fin.transaction_invoice_map,
    fin.transactions,
    fin.tax_invoices,
    fin.payment_requests,
    fin.claims
CASCADE;
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0031_finance_registry_system_keys")]
    operations = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
