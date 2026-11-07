"""Read-only evidence for one notice, mappings and an explicit tenant's list filters."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from procurement.models import CollectionRule, Notice
from procurement.preferences import selected_conditions, selected_ids
from procurement.service import central_alias, enabled, rule_matches
from procurement.tenant import query_notices
from geoflow_ops.bids import personal


class Command(BaseCommand):
    help = '공고 한 건의 저장·매칭·논리 조건·테넌트 목록 노출을 읽기 전용으로 확인합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--database', required=True)
        parser.add_argument('--user-id', help='개인 숨김까지 확인할 중앙 사용자 UUID (생략 시 회사 후보 목록만 확인)')
        parser.add_argument('--number', default='E012607882')
        parser.add_argument('--source', default='kepco')
        parser.add_argument('--api-response', help='별도로 확보한 실제 한전 API JSON 응답 파일')

    def handle(self, **options):
        tenant, central = options['database'], central_alias()
        if not enabled(tenant):
            raise CommandError('중앙 조회가 활성화된 명시적 테넌트가 필요합니다.')
        # Establish read-only transactions in both databases. Never collect or enqueue.
        with transaction.atomic(using=central), transaction.atomic(using=tenant):
            for alias in (central, tenant):
                if connections[alias].vendor == 'postgresql':
                    with connections[alias].cursor() as cur:
                        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            try:
                state = personal.rows(tenant, options['user_id'], 'central') if options['user_id'] else None
            except (ValueError, TypeError, AttributeError):
                raise CommandError('사용자 UUID를 확인하세요.') from None
            notice = Notice.objects.using(central).filter(source=options['source'], number=options['number']).first()
            rules = CollectionRule.objects.using(central).select_related('condition').filter(source=options['source'])
            result = {'number': options['number'], 'source': options['source'], 'api_received': None,
                      'central_stored': bool(notice), 'stored_rules': [], 'current_matches': [],
                      'logical_conditions': [], 'tenant_selected_conditions': selected_conditions(tenant),
                      'tenant_effective_rules': selected_ids(tenant), 'interest_match': False,
                      'personal_state_checked': state is not None,
                      'candidate_list_visible': False, 'candidate_list_visible_open_only': False}
            if options['api_response']:
                if options['source'] != 'kepco':
                    raise CommandError('API 파일 확인은 한전 응답에만 지원합니다.')
                try:
                    data = json.loads(Path(options['api_response']).read_text(encoding='utf-8'))['data']
                    if not isinstance(data, list):
                        raise ValueError()
                    result['api_received'] = any(str(item.get('no')) == options['number'] for item in data)
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    raise CommandError('실제 한전 API JSON 응답 형식을 확인하세요.') from None
            if notice:
                row = notice.raw.get('notice', {})
                details = {key: notice.raw.get(key, []) for key in ('industries', 'regions', 'products')}
                result['title'] = notice.title
                result['stored_rules'] = [str(pk) for pk in notice.rules.values_list('pk', flat=True)]
                for rule in rules:
                    if rule_matches(rule, row, details):
                        result['current_matches'].append({'rule_id': str(rule.pk), 'kind': rule.kind,
                                                          'value': rule.value, 'condition_key': rule.condition.key if rule.condition else None})
                result['logical_conditions'] = list(notice.rules.exclude(condition__isnull=True).values_list('condition__key',flat=True).distinct())
                result['interest_match'] = notice.rules.filter(pk__in=result['tenant_effective_rules']).exists()
                result['candidate_list_visible'] = query_notices(tenant, personal_state=state)[0].filter(pk=notice.pk).exists()
                result['candidate_list_visible_open_only'] = query_notices(tenant, include_closed=False, personal_state=state)[0].filter(pk=notice.pk).exists()
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
