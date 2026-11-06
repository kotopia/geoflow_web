"""Explicit identity backfill. Provider rules, activity, jobs and notice links stay intact."""
import re
from uuid import NAMESPACE_URL, uuid5

from django.db import migrations


MAPPINGS = {
    ('g2b', '5023'): ('public-survey', '공공측량업'),
    ('kepco', '공공측량업'): ('public-survey', '공공측량업'),
    ('g2b', '5031'): ('underground-survey', '지하시설물측량업'),
    ('kepco', '지하시설물측량업'): ('underground-survey', '지하시설물측량업'),
    ('g2b', '5029'): ('digital-map', '수치지도제작업'),
    ('kepco', '수치지도제작업'): ('digital-map', '수치지도제작업'),
    ('g2b', '1468'): ('software-business', '소프트웨어사업자'),
}


def forwards(apps, schema_editor):
    Rule = apps.get_model('procurement', 'CollectionRule')
    Condition = apps.get_model('procurement', 'InterestCondition')
    alias = schema_editor.connection.alias
    for rule in Rule.objects.using(alias).order_by('created_at', 'pk').iterator():
        if rule.condition_id:
            continue
        if rule.kind == 'keyword':
            term = re.sub(r'\s+', '', rule.value).casefold()
            key, name = 'keyword-' + uuid5(NAMESPACE_URL, term).hex, rule.value.strip()
        else:
            key, name = MAPPINGS.get((rule.source, rule.value), ('legacy-' + rule.pk.hex, rule.name))
        condition, created = Condition.objects.using(alias).get_or_create(
            kind=rule.kind, key=key,
            defaults={'id': uuid5(NAMESPACE_URL, f'geoflow:bid-interest:{rule.kind}:{key}'),
                      'name': name, 'active': rule.active})
        if not created and rule.active and not condition.active:
            Condition.objects.using(alias).filter(pk=condition.pk).update(active=True)
        Rule.objects.using(alias).filter(pk=rule.pk).update(condition_id=condition.pk)


class Migration(migrations.Migration):
    dependencies = [('procurement', '0006_interestcondition_collectionrule_condition')]
    # Tenant references are outside the central transaction. Unbind only after
    # restoring tenant backups and rolling application code back.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
