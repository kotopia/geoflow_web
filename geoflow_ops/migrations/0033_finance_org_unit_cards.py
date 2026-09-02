from django.db import migrations


SQL = r"""
ALTER TABLE fin.accounts ADD COLUMN IF NOT EXISTS my_org_unit_id uuid NULL;
ALTER TABLE fin.claims ADD COLUMN IF NOT EXISTS my_org_unit_id uuid NULL;
ALTER TABLE fin.payment_requests ADD COLUMN IF NOT EXISTS my_org_unit_id uuid NULL;
ALTER TABLE fin.tax_invoices ADD COLUMN IF NOT EXISTS my_org_unit_id uuid NULL;
ALTER TABLE fin.transactions ADD COLUMN IF NOT EXISTS my_org_unit_id uuid NULL;

CREATE INDEX IF NOT EXISTS idx_fin_accounts_org ON fin.accounts(my_org_unit_id);
CREATE INDEX IF NOT EXISTS idx_fin_claim_org ON fin.claims(my_org_unit_id);
CREATE INDEX IF NOT EXISTS idx_fin_payreq_org ON fin.payment_requests(my_org_unit_id);
CREATE INDEX IF NOT EXISTS idx_fin_invoice_org ON fin.tax_invoices(my_org_unit_id);
CREATE INDEX IF NOT EXISTS idx_fin_tx_org ON fin.transactions(my_org_unit_id);

UPDATE fin.claims f
SET my_org_unit_id = c.org_unit_id
FROM ctr.contracts c
WHERE f.contract_id=c.id AND f.my_org_unit_id IS NULL AND c.org_unit_id IS NOT NULL;

UPDATE fin.payment_requests f
SET my_org_unit_id = c.org_unit_id
FROM ctr.contracts c
WHERE f.contract_id=c.id AND f.my_org_unit_id IS NULL AND c.org_unit_id IS NOT NULL;

UPDATE fin.tax_invoices f
SET my_org_unit_id = c.org_unit_id
FROM ctr.contracts c
WHERE f.contract_id=c.id AND f.my_org_unit_id IS NULL AND c.org_unit_id IS NOT NULL;

UPDATE fin.transactions f
SET my_org_unit_id = c.org_unit_id
FROM ctr.contracts c
WHERE f.contract_id=c.id AND f.my_org_unit_id IS NULL AND c.org_unit_id IS NOT NULL;

DO $$
DECLARE
  only_org uuid;
BEGIN
  SELECT id INTO only_org
    FROM ops.my_org_units
   WHERE (SELECT count(*) FROM ops.my_org_units)=1
   LIMIT 1;
  IF only_org IS NOT NULL THEN
    UPDATE fin.accounts SET my_org_unit_id=only_org WHERE my_org_unit_id IS NULL;
    UPDATE fin.claims SET my_org_unit_id=only_org WHERE my_org_unit_id IS NULL;
    UPDATE fin.payment_requests SET my_org_unit_id=only_org WHERE my_org_unit_id IS NULL;
    UPDATE fin.tax_invoices SET my_org_unit_id=only_org WHERE my_org_unit_id IS NULL;
    UPDATE fin.transactions SET my_org_unit_id=only_org WHERE my_org_unit_id IS NULL;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS fin.cards (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    my_org_unit_id uuid NOT NULL,
    issuer varchar(120) NOT NULL,
    card_name varchar(150) NOT NULL,
    masked_number varchar(80) NULL,
    active boolean NOT NULL DEFAULT true,
    memo text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_cards_org ON fin.cards(my_org_unit_id);
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0032_finance_edit_delete_import_v2")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
