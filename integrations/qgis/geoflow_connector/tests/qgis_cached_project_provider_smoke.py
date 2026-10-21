"""Read-only provider smoke for an existing cached GeoPackage."""
import sqlite3
import sys
from pathlib import Path

from qgis.core import QgsApplication, QgsVectorLayer


def main(path):
    package = Path(path).resolve()
    uri = package.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        layers = [str(row[0]) for row in connection.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' "
            "ORDER BY table_name"
        )]
        tables = {str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        counts = {}
        for label, table in (
            ("pending", "_geoflow_pending_change"),
            ("outbox", "_geoflow_outbox"),
            ("conflict", "_geoflow_conflict"),
        ):
            counts[label] = (int(connection.execute(
                f'SELECT count(*) FROM "{table}"'
            ).fetchone()[0]) if table in tables else 0)

    application = QgsApplication([], False)
    application.initQgis()
    try:
        valid = [name for name in layers if QgsVectorLayer(
            f"{package}|layername={name}", name, "ogr"
        ).isValid()]
        print({"layers": len(layers), "valid": len(valid), "queue": counts})
        if len(valid) != len(layers):
            return 1
    finally:
        application.exitQgis()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
