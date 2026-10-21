"""Display documented row fields without assuming a response envelope name.

This is a read-only projection, not an upload/import protocol decoder. Unknown
structures stay in the raw response view; no field aliases are guessed.
"""
from uuid import UUID


def display_rows(payload, kind):
    required = {"sources": {"id", "original_file_name"},
                "points": {"id", "source_row_id"}}[kind]
    result = []
    def visit(value):
        if isinstance(value, dict):
            if required <= value.keys():
                try:
                    UUID(str(value["id"]))
                except (ValueError, TypeError):
                    return
                result.append(value)
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(payload)
    return result
