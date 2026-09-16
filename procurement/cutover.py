"""Run inside the deployment's existing tenant transaction, including dry-run."""
import json

from .policy import notice_id, canonical_order
from .models import CollectionRule
from .service import central_alias
from geoflow_ops.bids.sync import _detail_url


def prepare(cur):
    cur.execute("""SELECT n.id::text,n.bid_notice_no,n.bid_notice_ord,n.title,n.detail_url,
                   r.status,COALESCE(r.memo,''),COALESCE(r.updated_by,''),r.updated_at
                   FROM bid.notice_reviews r JOIN bid.notices n ON n.id=r.notice_id
                   WHERE n.source='g2b' AND n.business_type='service'""")
    reviews = cur.fetchall()
    ids = [str(notice_id(row[1], row[2])) for row in reviews]
    if len(ids) != len(set(ids)):
        raise ValueError("차수 정규화 후 검토기록 충돌: 수동 검토가 필요합니다.")
    for row, pk in zip(reviews, ids):
        cur.execute("""INSERT INTO bid.central_reviews
          (central_notice_id,legacy_notice_id,notice_number,notice_order,title,detail_url,
           status,memo,updated_by,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(central_notice_id) DO NOTHING""",
          [pk, row[0], row[1], canonical_order(row[2]), row[3], _detail_url(row[4]), *row[5:]])
    cur.execute("SELECT code FROM bid.filter_values WHERE kind='industry' AND active=true")
    codes = [row[0] for row in cur.fetchall()]
    selected = [str(pk) for pk in CollectionRule.objects.using(central_alias()).filter(
        kind='industry', value__in=codes, active=True).values_list('pk', flat=True)]
    cur.execute("""INSERT INTO bid.central_preferences(id,rule_ids) VALUES (1,%s::jsonb)
                   ON CONFLICT(id) DO NOTHING""", [json.dumps(selected)])
    cur.execute("SELECT count(*) FROM bid.central_reviews WHERE central_notice_id=ANY(%s::uuid[])", [ids])
    if cur.fetchone()[0] != len(ids):
        raise ValueError("검토기록 매핑 수량이 일치하지 않습니다.")
    cur.execute("SELECT jsonb_array_length(rule_ids) FROM bid.central_preferences WHERE id=1")
    return {"legacy_reviews_preserved": len(reviews), "selected_rules": cur.fetchone()[0]}
