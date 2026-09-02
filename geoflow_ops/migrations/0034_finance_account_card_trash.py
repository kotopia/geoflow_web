from django.db import migrations


SQL = r"""
ALTER TABLE fin.accounts ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false;
ALTER TABLE fin.accounts ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL;
ALTER TABLE fin.accounts ADD COLUMN IF NOT EXISTS deleted_by varchar(255) NULL;

ALTER TABLE fin.cards ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false;
ALTER TABLE fin.cards ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL;
ALTER TABLE fin.cards ADD COLUMN IF NOT EXISTS deleted_by varchar(255) NULL;

UPDATE fin.accounts
   SET is_deleted=true, deleted_at=COALESCE(deleted_at, now())
 WHERE active=false AND is_deleted=false;

UPDATE fin.cards
   SET is_deleted=true, deleted_at=COALESCE(deleted_at, now())
 WHERE active=false AND is_deleted=false;

CREATE INDEX IF NOT EXISTS idx_fin_accounts_deleted ON fin.accounts(is_deleted, bank_name, account_name);
CREATE INDEX IF NOT EXISTS idx_fin_cards_deleted ON fin.cards(is_deleted, issuer, card_name);
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0033_finance_org_unit_cards")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
