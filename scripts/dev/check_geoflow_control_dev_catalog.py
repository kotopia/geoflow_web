"""Read-only verifier for the central GeoFlow catalog required by tenant runtime."""
from __future__ import annotations

import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

import django

django.setup()

from django.db import connections


def main() -> int:
    with connections["default"].cursor() as cursor:
        cursor.execute("select current_database()")
        database = cursor.fetchone()[0]
        cursor.execute(
            """
            select
                to_regclass('catalog.category_node'),
                to_regclass('catalog.category_parent'),
                to_regclass('catalog.category_facet_option'),
                to_regclass('catalog.category_option_set')
            """
        )
        relations = cursor.fetchone()
        if any(value is None for value in relations):
            missing = [
                name
                for name, value in zip(
                    (
                        "catalog.category_node",
                        "catalog.category_parent",
                        "catalog.category_facet_option",
                        "catalog.category_option_set",
                    ),
                    relations,
                )
                if value is None
            ]
            raise SystemExit("central catalog missing: " + ", ".join(missing))

        cursor.execute("select count(*) from catalog.category_node")
        node_count = cursor.fetchone()[0]
        cursor.execute("select count(*) from catalog.category_facet_option")
        option_count = cursor.fetchone()[0]

    print(f"central_catalog_db={database}")
    print(f"catalog_category_nodes={node_count}")
    print(f"catalog_facet_options={option_count}")
    if node_count <= 0:
        raise SystemExit("central catalog.category_node is empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
