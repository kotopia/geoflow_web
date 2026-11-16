"""Save a reviewed result to a new GeoPackage with embedded provenance."""
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory
from qgis.core import QgsProject, QgsVectorFileWriter


def save_geopackage(layer, destination):
    path = Path(destination)
    if path.exists():
        raise ValueError('새 GeoPackage 파일명을 지정하세요. 기존 파일은 덮어쓰지 않습니다.')
    prefix = 'geoflow_qc_structure/'
    metadata = {key: json.loads(layer.customProperty(prefix + key))
                for key in ('profile', 'output_fields', 'aggregate_details', 'dependencies')}
    with TemporaryDirectory(dir=path.parent, prefix='geoflow-output-') as directory:
        staged = Path(directory) / 'result.gpkg'
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = 'structured'
        result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(staged), QgsProject.instance().transformContext(), options)
        if result[0] != QgsVectorFileWriter.WriterError.NoError:
            raise ValueError(f'GeoPackage 저장 실패: {result}')
        # Use a scoped GDAL handle: QGIS's OGR connection pool keeps files locked on Windows.
        from osgeo import gdal
        from datetime import date, datetime
        from .ui_values import scalar
        names = layer.fields().names()
        expected = [(tuple(scalar(f[n]) for n in names), bytes(f.geometry().asWkb())) for f in layer.getFeatures()]
        with gdal.OpenEx(str(staged), gdal.OF_VECTOR | gdal.OF_READONLY) as dataset:
            check = dataset.GetLayerByName('structured')
            if check is None or check.GetFeatureCount() != layer.featureCount():
                raise ValueError('GeoPackage 재조회 검증 실패')
            actual = []
            for feature, (values, _) in zip(check, expected):
                converted = []
                for name, original in zip(names, values):
                    value = feature.GetField(name)
                    if value is not None and isinstance(original, datetime):
                        value = datetime.fromisoformat(value.replace('/', '-'))
                    elif value is not None and isinstance(original, date):
                        value = date.fromisoformat(value.replace('/', '-'))
                    converted.append(value)
                geometry = feature.GetGeometryRef()
                actual.append((tuple(converted), bytes(geometry.ExportToIsoWkb()) if geometry else b''))
        if expected != actual:
            raise ValueError('GeoPackage 값 또는 도형 불일치')
        with closing(sqlite3.connect(staged)) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS gpkg_metadata (
                    id INTEGER CONSTRAINT m_pk PRIMARY KEY ASC NOT NULL,
                    md_scope TEXT NOT NULL DEFAULT 'dataset', md_standard_uri TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'text/xml', metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS gpkg_metadata_reference (
                    reference_scope TEXT NOT NULL, table_name TEXT, column_name TEXT, row_id_value INTEGER,
                    timestamp DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    md_file_id INTEGER NOT NULL, md_parent_id INTEGER);
                CREATE TABLE IF NOT EXISTS gpkg_extensions (
                    table_name TEXT, column_name TEXT, extension_name TEXT NOT NULL,
                    definition TEXT NOT NULL, scope TEXT NOT NULL,
                    CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name));
            ''')
            for table in ('gpkg_metadata', 'gpkg_metadata_reference'):
                db.execute('INSERT INTO gpkg_extensions VALUES (?, NULL, ?, ?, ?)',
                           (table, 'gpkg_metadata', 'http://www.geopackage.org/spec/#extension_metadata', 'read-write'))
            cursor = db.execute('INSERT INTO gpkg_metadata (md_scope,md_standard_uri,mime_type,metadata) VALUES (?,?,?,?)',
                ('dataset', 'https://geoflow.co.kr/qc-structure/local-pilot', 'application/json', json.dumps(metadata, ensure_ascii=False)))
            db.execute('INSERT INTO gpkg_metadata_reference (reference_scope,table_name,md_file_id) VALUES (?,?,?)',
                       ('table', 'structured', cursor.lastrowid))
        os.link(staged, path)  # Exclusive atomic install; never overwrite a source/result.
    return path
