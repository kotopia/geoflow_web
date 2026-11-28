from django.db import migrations


SQL = """
CREATE TABLE fin.allocations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id uuid REFERENCES fin.tax_invoices ON DELETE CASCADE,
    transaction_id uuid REFERENCES fin.transactions ON DELETE CASCADE,
    claim_id uuid REFERENCES fin.claims,
    payment_request_id uuid REFERENCES fin.payment_requests,
    amount numeric(18,0) NOT NULL CHECK (amount > 0),
    CHECK (num_nonnulls(invoice_id,transaction_id)=1),
    CHECK (num_nonnulls(claim_id,payment_request_id)=1)
);
CREATE INDEX ON fin.allocations(invoice_id);
CREATE INDEX ON fin.allocations(transaction_id);
CREATE INDEX ON fin.allocations(claim_id);
CREATE INDEX ON fin.allocations(payment_request_id);

CREATE VIEW fin.confirmed_links AS
SELECT a.invoice_id,a.transaction_id,a.claim_id,a.payment_request_id,a.amount
FROM fin.allocations a
LEFT JOIN fin.tax_invoices i ON a.invoice_id=i.id
LEFT JOIN fin.transactions t ON a.transaction_id=t.id
WHERE NOT COALESCE(i.is_deleted,t.is_deleted,true)
UNION ALL
SELECT id,NULL,claim_id,payment_request_id,total_amount FROM fin.tax_invoices
WHERE NOT is_deleted AND num_nonnulls(claim_id,payment_request_id)>0
UNION ALL
SELECT NULL,id,claim_id,payment_request_id,amount FROM fin.transactions
WHERE NOT is_deleted AND num_nonnulls(claim_id,payment_request_id)>0;

CREATE VIEW fin.issued_invoice_links AS
SELECT l.* FROM fin.confirmed_links l JOIN fin.tax_invoices i ON i.id=l.invoice_id
WHERE i.status IS DISTINCT FROM COALESCE((SELECT code FROM ops.settings_nodes
    WHERE system_key='finance.value.invoice_status.cancelled' AND active LIMIT 1),'cancelled')
AND (i.issued_date IS NOT NULL OR NULLIF(i.approval_no,'') IS NOT NULL OR i.status=COALESCE(
    (SELECT code FROM ops.settings_nodes WHERE system_key='finance.value.invoice_status.issued' AND active LIMIT 1),'issued'));

CREATE VIEW fin.settlements AS
SELECT claim_id,payment_request_id,
       COALESCE(sum(amount) FILTER (WHERE transaction_id IS NOT NULL),0) AS settled
FROM fin.confirmed_links GROUP BY claim_id,payment_request_id;

ALTER TABLE fin.claims ADD COLUMN installment integer CHECK (installment>0);
CREATE TABLE fin.claim_documents (
    claim_id uuid NOT NULL REFERENCES fin.claims ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('bill','statement')),
    contents jsonb NOT NULL,
    issued_at timestamptz NOT NULL DEFAULT now(),
    submitted_at timestamptz,
    PRIMARY KEY(claim_id,kind)
);
ALTER TABLE fin.payment_requests ADD COLUMN bill_attachment_id uuid, ADD COLUMN statement_attachment_id uuid;
ALTER TABLE fin.accounts ADD COLUMN attachment_id uuid, ADD COLUMN holder text;
ALTER TABLE fin.cards ADD COLUMN attachment_id uuid, ADD COLUMN custodian text,
    ADD COLUMN settlement_account_id uuid REFERENCES fin.accounts;
UPDATE ops.settings_nodes SET name='선급금'
WHERE system_key='finance.value.claim_type.advance' AND name='선금';
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0058_merge_bid_progress")]
    operations = [migrations.RunSQL(SQL)]
