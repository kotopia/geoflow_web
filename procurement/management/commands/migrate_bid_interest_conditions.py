"""Explicit per-tenant conversion using the existing JSON preference column."""
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from procurement.conditions import canonical_ids
from procurement.service import enabled


class Command(BaseCommand):
    help = '기존 기관별 관심조건 UUID를 논리 관심조건 UUID로 변환합니다. 기본 읽기 전용.'

    def add_arguments(self, parser):
        parser.add_argument('--database', required=True)
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--backup-file')
        parser.add_argument('--restore-file')

    def handle(self, **options):
        alias = options['database']
        if not enabled(alias):
            raise CommandError('중앙 조회가 활성화된 명시적 테넌트가 필요합니다.')
        conn = connections[alias]
        if conn.vendor != 'postgresql':
            raise CommandError('설정 변환은 PostgreSQL에서 실행하세요.')
        with transaction.atomic(using=alias), conn.cursor() as cur:
            if options['execute']:
                cur.execute('LOCK TABLE bid.central_preferences IN SHARE ROW EXCLUSIVE MODE')
            cur.execute('SELECT rule_ids FROM bid.central_preferences WHERE id=1')
            row = cur.fetchone()
            before = json.loads(row[0]) if row and isinstance(row[0], str) else row[0] if row else None
            if before is None:
                self.stdout.write('preferences=absent; legacy industry fallback preserved; changes=0')
                return
            try:
                after = canonical_ids(before, strict=True)
            except (ValueError, TypeError, AttributeError) as exc:
                raise CommandError(str(exc)) from None
            if options['restore_file']:
                try:
                    backup = json.loads(Path(options['restore_file']).read_text(encoding='utf-8'))
                    if not isinstance(backup['before'], list) or not isinstance(backup['after'], list):
                        raise ValueError()
                except (OSError, ValueError, TypeError, KeyError):
                    raise CommandError('복원 백업 파일 형식을 확인하세요.') from None
                if backup['database'] != alias or sorted(before) != sorted(backup['after']):
                    raise CommandError('백업 대상 또는 현재 설정이 다릅니다. 이후 변경을 덮어쓰지 않습니다.')
                after = backup['before']
            changed = sorted(before) != sorted(after)
            if options['execute'] and changed:
                if not options['backup_file']:
                    raise CommandError('--backup-file이 필요합니다.')
                path = Path(options['backup_file'])
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except OSError:
                    raise CommandError('새 백업 파일을 생성하지 못했습니다. 설정은 변경하지 않았습니다.') from None
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump({'database': alias, 'before': before, 'after': after}, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                cur.execute('UPDATE bid.central_preferences SET rule_ids=%s::jsonb,updated_at=now() WHERE id=1',
                            [json.dumps(after)])
            self.stdout.write(f'previous={len(before)}; logical={len(after)}; changes={int(changed)}; '
                              f'applied={bool(options["execute"] and changed)}')
