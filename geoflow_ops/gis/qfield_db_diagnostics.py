"""Log database failure identifiers without SQL, row values, or credentials."""
import logging

logger = logging.getLogger(__name__)


def log_changeset_database_error(exc):
    cause = exc.__cause__ or exc
    diag = getattr(cause, 'diag', None)
    logger.error(
        'QField changeset database failure: type=%s sqlstate=%s schema=%s table=%s column=%s constraint=%s',
        type(cause).__name__,
        getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None),
        getattr(diag, 'schema_name', None),
        getattr(diag, 'table_name', None),
        getattr(diag, 'column_name', None),
        getattr(diag, 'constraint_name', None),
    )
