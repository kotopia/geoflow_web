from django.db import migrations


FORWARD_SQL = r"""
CREATE SCHEMA IF NOT EXISTS fin;

CREATE TABLE IF NOT EXISTS fin.accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    bank_name varchar(100) NOT NULL,
    account_name varchar(150) NOT NULL,
    account_number varchar(100) NULL,
    currency varchar(10) NOT NULL DEFAULT 'KRW',
    active boolean NOT NULL DEFAULT true,
    memo text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fin.claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id uuid NOT NULL,
    project_id uuid NULL,
    partner_id uuid NULL,
    claim_date date NULL,
    due_date date NULL,
    expected_receipt_date date NULL,
    title varchar(255) NOT NULL,
    claim_type varchar(80) NULL,
    supply_amount numeric(18,0) NOT NULL DEFAULT 0,
    vat_amount numeric(18,0) NOT NULL DEFAULT 0,
    total_amount numeric(18,0) NOT NULL DEFAULT 0,
    status varchar(80) NULL,
    memo text NULL,
    created_by varchar(255) NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_claim_contract ON fin.claims(contract_id);
CREATE INDEX IF NOT EXISTS idx_fin_claim_project ON fin.claims(project_id);
CREATE INDEX IF NOT EXISTS idx_fin_claim_partner ON fin.claims(partner_id);

CREATE TABLE IF NOT EXISTS fin.payment_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id uuid NULL,
    project_id uuid NULL,
    partner_id uuid NULL,
    request_date date NULL,
    due_date date NULL,
    title varchar(255) NOT NULL,
    amount numeric(18,0) NOT NULL DEFAULT 0,
    category_code varchar(120) NULL,
    status varchar(80) NULL,
    memo text NULL,
    created_by varchar(255) NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fin_payreq_contract ON fin.payment_requests(contract_id);
CREATE INDEX IF NOT EXISTS idx_fin_payreq_project ON fin.payment_requests(project_id);
CREATE INDEX IF NOT EXISTS idx_fin_payreq_partner ON fin.payment_requests(partner_id);

CREATE TABLE IF NOT EXISTS fin.tax_invoices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    written_date date NULL,
    issued_date date NULL,
    invoice_type varchar(80) NOT NULL,
    partner_id uuid NULL,
    contract_id uuid NULL,
    project_id uuid NULL,
    claim_id uuid NULL,
    payment_request_id uuid NULL,
    supply_amount numeric(18,0) NOT NULL DEFAULT 0,
    vat_amount numeric(18,0) NOT NULL DEFAULT 0,
    total_amount numeric(18,0) NOT NULL DEFAULT 0,
    approval_no varchar(120) NULL,
    status varchar(80) NULL,
    attachment_id uuid NULL,
    memo text NULL,
    created_by varchar(255) NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_fin_invoice_related_one CHECK (claim_id IS NULL OR payment_request_id IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fin_invoice_contract ON fin.tax_invoices(contract_id);
CREATE INDEX IF NOT EXISTS idx_fin_invoice_claim ON fin.tax_invoices(claim_id);
CREATE INDEX IF NOT EXISTS idx_fin_invoice_payreq ON fin.tax_invoices(payment_request_id);

CREATE TABLE IF NOT EXISTS fin.transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_date date NOT NULL,
    transaction_type varchar(80) NOT NULL,
    amount numeric(18,0) NOT NULL,
    partner_id uuid NULL,
    account_id uuid NULL REFERENCES fin.accounts(id) ON DELETE SET NULL,
    description varchar(500) NULL,
    contract_id uuid NULL,
    project_id uuid NULL,
    claim_id uuid NULL,
    payment_request_id uuid NULL,
    category_code varchar(120) NULL,
    evidence_type varchar(120) NULL,
    evidence_attachment_id uuid NULL,
    memo text NULL,
    created_by varchar(255) NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_fin_tx_related_one CHECK (claim_id IS NULL OR payment_request_id IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fin_tx_date ON fin.transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_fin_tx_contract ON fin.transactions(contract_id);
CREATE INDEX IF NOT EXISTS idx_fin_tx_claim ON fin.transactions(claim_id);
CREATE INDEX IF NOT EXISTS idx_fin_tx_payreq ON fin.transactions(payment_request_id);

CREATE TABLE IF NOT EXISTS fin.transaction_invoice_map (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id uuid NOT NULL REFERENCES fin.transactions(id) ON DELETE CASCADE,
    invoice_id uuid NOT NULL REFERENCES fin.tax_invoices(id) ON DELETE CASCADE,
    allocated_amount numeric(18,0) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(transaction_id, invoice_id)
);

INSERT INTO ops.settings_nodes (code,name,node_type,system_key,ord,locked)
SELECT 'finance','파이낸스','group','domain.finance',40,true
WHERE NOT EXISTS (SELECT 1 FROM ops.settings_nodes WHERE system_key='domain.finance');

INSERT INTO ops.settings_nodes (parent_id,code,name,node_type,field_ref,ord,locked)
SELECT root.id, s.code, s.name, 'category', s.field_ref, s.ord, true
FROM ops.settings_nodes root
CROSS JOIN (VALUES
 ('claim_type','청구구분','finance.claim_type',10),
 ('claim_status','청구상태','finance.claim_status',20),
 ('invoice_type','세금계산서 구분','finance.invoice_type',30),
 ('invoice_status','세금계산서 상태','finance.invoice_status',40),
 ('payment_status','지급상태','finance.payment_status',50),
 ('transaction_type','입출금 구분','finance.transaction_type',60),
 ('transaction_category','수입·지출 분류','finance.transaction_category',70),
 ('evidence_type','증빙유형','finance.evidence_type',80)
) s(code,name,field_ref,ord)
WHERE root.system_key='domain.finance'
  AND NOT EXISTS (SELECT 1 FROM ops.settings_nodes x WHERE x.field_ref=s.field_ref);

INSERT INTO ops.settings_nodes (parent_id,code,name,node_type,ord)
SELECT c.id, s.code, s.name, 'value', s.ord
FROM ops.settings_nodes c
JOIN (VALUES
 ('finance.claim_type','advance','선금',10),('finance.claim_type','progress','기성금',20),('finance.claim_type','final','준공금',30),('finance.claim_type','additional','추가청구',40),('finance.claim_type','other','기타',90),
 ('finance.claim_status','planned','예정',10),('finance.claim_status','claimed','청구',20),('finance.claim_status','invoiced','계산서발행',30),('finance.claim_status','partial','일부수금',40),('finance.claim_status','received','수금완료',50),('finance.claim_status','cancelled','취소',90),
 ('finance.invoice_type','sales','매출',10),('finance.invoice_type','purchase','매입',20),
 ('finance.invoice_status','planned','예정',10),('finance.invoice_status','issued','발행',20),('finance.invoice_status','cancelled','취소',90),
 ('finance.payment_status','planned','예정',10),('finance.payment_status','requested','요청',20),('finance.payment_status','approved','승인',30),('finance.payment_status','partial','일부지급',40),('finance.payment_status','paid','지급완료',50),('finance.payment_status','cancelled','취소',90),
 ('finance.transaction_type','in','입금',10),('finance.transaction_type','out','출금',20),
 ('finance.transaction_category','contract_payment','계약대금',10),('finance.transaction_category','outsourcing','외주비',20),('finance.transaction_category','labor','인건비',30),('finance.transaction_category','equipment','장비비',40),('finance.transaction_category','vehicle','차량비',50),('finance.transaction_category','travel','교통·숙박비',60),('finance.transaction_category','supplies','소모품비',70),('finance.transaction_category','tax','세금·공과금',80),('finance.transaction_category','other','기타',90),
 ('finance.evidence_type','tax_invoice','세금계산서',10),('finance.evidence_type','card','카드전표',20),('finance.evidence_type','cash_receipt','현금영수증',30),('finance.evidence_type','receipt','영수증',40),('finance.evidence_type','transfer','이체확인증',50),('finance.evidence_type','statement','거래명세서',60),('finance.evidence_type','bill','청구서',70),('finance.evidence_type','other','기타',80),('finance.evidence_type','none','없음',90)
) s(field_ref,code,name,ord) ON c.field_ref=s.field_ref
WHERE NOT EXISTS (SELECT 1 FROM ops.settings_nodes x WHERE x.parent_id=c.id AND x.code=s.code);
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0029_unified_settings_registry")]
    operations = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
