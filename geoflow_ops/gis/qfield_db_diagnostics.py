"""Log database failure identifiers without SQL, row values, or credentials."""
import logging
import re
import traceback

logger = logging.getLogger(__name__)


def log_changeset_database_error(exc):
    cause = exc.__cause__ or exc
    diag = getattr(cause, 'diag', None)
    # PostgreSQL often omits table/column for 22P02. Extract only a fixed
    # allowlist of type names; never log message_primary (which contains values).
    primary = str(getattr(diag, 'message_primary', '') or '')
    match = re.search(r'invalid input syntax for type (uuid|integer|bigint|smallint|numeric|real|double precision|boolean|json|jsonb)(?=:)', primary)
    target_type = match.group(1) if match else 'unknown'
    frames = traceback.extract_tb(exc.__traceback__)
    location = ' > '.join(
        f'{frame.name}:{frame.lineno}' for frame in frames
        if '/geoflow_ops/gis/' in frame.filename.replace('\\', '/')
    ) or 'unavailable'
    logger.error(
        'QField changeset database failure: type=%s sqlstate=%s schema=%s table=%s column=%s constraint=%s target_type=%s location=%s',
        type(cause).__name__,
        getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None),
        getattr(diag, 'schema_name', None),
        getattr(diag, 'table_name', None),
        getattr(diag, 'column_name', None),
        getattr(diag, 'constraint_name', None),
        target_type, location,
    )
