"""QGIS application fixture: exact stored-depth aggregation and object preview."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import os

from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.utils import iface, plugins
from geoflow_qc_structure.spatial import Spatial
from geoflow_qc_structure.preview_table import dependency_snapshot, display
from geoflow_qc_structure.references import CodeBooks

project = QgsProject.instance()
window = plugins['geoflow_qc_structure'].window
pipe = QgsVectorLayer('LineString?crs=EPSG:5186&field=code:string', 'pipe', 'memory')
depth = QgsVectorLayer('Point?crs=EPSG:5186&field=stored:double', 'stored source', 'memory')
owned = [pipe, depth]


def add(layer, wkt, value):
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromWkt(wkt))
    f.setAttributes([value])
    ok, features = layer.dataProvider().addFeatures([f])
    assert ok
    layer.updateExtents()
    return features[0].id()


try:
    fid = add(pipe, 'LINESTRING (200000 500000, 200010 500000)', 'SA203')
    ids = [add(depth, f'POINT ({200001+i} 500000)', v) for i, v in enumerate([None, 0, -2, 5, 5])]
    for layer in owned:
        project.addMapLayer(layer)
    params = dict(reference_layer=depth.id(), reference_field='stored', crs='EPSG:5186', radius=0.1,
                  selection_policy='unique', scope='all', statistic='mean', unit='m')
    spatial = Spatial(pipe)
    geom = pipe.getFeature(fid).geometry()
    result = spatial.aggregate(geom, params)
    from geoflow_qc_structure.operation_editor import AggregateSettings
    widget = AggregateSettings(window, params)
    configured = widget.parameters('EPSG:5186')
    Spatial(pipe).validate_aggregate(configured)
    for bad in [dict(params, reference_layer='missing'), dict(params, reference_field='missing'),
                dict(params, crs='EPSG:4326'), dict(params, unit='unknown'), dict(params, radius=-1)]:
        try:
            Spatial(pipe).validate_aggregate(bad)
            raise AssertionError('Invalid aggregate input accepted')
        except ValueError:
            pass
    assert (result['mean'], result['minimum'], result['maximum']) == (Decimal(2), -2, 5)
    assert (result['searched'], result['valid'], result['excluded']) == (5, 4, 1)
    assert len(result['sources']) == 5
    for stat in ['mean', 'minimum', 'maximum']:
        spatial.aggregate(geom, dict(params, statistic=stat))
    assert spatial.aggregate_searches == 1
    pipe_before = [(f.id(), f.attributes(), bytes(f.geometry().asWkb())) for f in pipe.getFeatures()]
    window.reload_layers()
    window.layers.setCurrentIndex(window.layers.findData(pipe.id()))
    profile = deepcopy(window.current_profile())
    profile['base_profile_id'] = None
    profile['field_rules'] = {}
    profile['qc_rules'] = {}
    for stat in ['mean', 'minimum', 'maximum']:
        profile['field_rules'][stat] = dict(operation='AGGREGATE', params=dict(params, statistic=stat),
            field=dict(semantic_key=stat, physical_name=stat, data_type='NUMERIC', precision=5, scale=2, nullable=True))
    profile['field_rules']['facility'] = dict(operation='COPY', params=dict(source_field='code'),
        field=dict(semantic_key='facility', physical_name='facility', data_type='TEXT', nullable=True))
    for name, value in [('empty', ''), ('null', None), ('zero', 0)]:
        profile['field_rules'][name] = dict(operation='CONSTANT', params=dict(value=value),
            field=dict(semantic_key=name, physical_name=name, data_type='INTEGER' if name == 'zero' else 'TEXT', nullable=True))
    window.raw_profile = profile
    window.prepare()
    assert window.object_table.rowCount() == 1
    assert [window.object_table.horizontalHeaderItem(i).text() for i in range(7)] == list(profile['field_rules'])
    assert [window.object_table.item(0, i).text() for i in range(7)] == ['2.00', '-2.00', '5.00', 'SA203', '""', 'NULL', '0']
    assert window.object_table.item(0, 0).background().color().name() == '#fff1b8'
    window.object_table.setCurrentCell(0, 0)
    window.select_preview()
    assert pipe.selectedFeatureIds() == [fid]
    window.pan_preview()
    window.zoom_preview()
    before = set(project.mapLayers())
    window.execute()
    new = set(project.mapLayers()) - before
    assert len(new) == 1
    output = project.mapLayer(new.pop())
    owned.append(output)
    assert next(output.getFeatures()).attributes()[:4] == [2.0, -2.0, 5.0, 'SA203']
    assert output.customProperty('geoflow_qc_structure/aggregate_details')
    from geoflow_qc_structure.output import save_geopackage
    import sqlite3, json
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'result.gpkg'
        save_geopackage(output, path)
        from contextlib import closing
        with closing(sqlite3.connect(path)) as db:
            saved = json.loads(db.execute("SELECT metadata FROM gpkg_metadata WHERE mime_type='application/json'").fetchone()[0])
            assert saved['profile']['field_rules']['mean']['params']['reference_layer'] == depth.id()
        try:
            save_geopackage(output, path)
            raise AssertionError('Existing result overwritten')
        except ValueError:
            pass
    # Reference edit changes fingerprint even when numeric aggregate remains identical.
    window.prepare()
    old = window.preview_state
    depth.dataProvider().changeAttributeValues({ids[1]: {0: -2}, ids[2]: {0: 0}})
    assert window.calculate()[-1] != old
    before = set(project.mapLayers())
    try:
        window.execute()
        raise AssertionError('Stale preview executed')
    except ValueError:
        pass
    assert set(project.mapLayers()) == before
    # Parallel and crossing candidates are review errors; no arbitrary first candidate.
    for wkt in ['LINESTRING (200000 500000.05, 200010 500000.05)', 'LINESTRING (200003 499999, 200003 500001)']:
        other = add(pipe, wkt, 'SA200')
        try:
            Spatial(pipe).aggregate(geom, params)
            raise AssertionError('Ambiguous candidates accepted')
        except ValueError:
            pass
        pipe.dataProvider().deleteFeatures([other])
    other = add(pipe, 'LINESTRING (200000 500000.05, 200010 500000.05)', 'SA200')
    assert Spatial(pipe).aggregate(geom, dict(params, selection_policy='nearest'))['valid'] == 4
    pipe.dataProvider().deleteFeatures([other])
    other = add(pipe, 'LINESTRING (200000 500000, 200010 500000)', 'SA200')
    try:
        Spatial(pipe).aggregate(geom, dict(params, selection_policy='nearest'))
        raise AssertionError('Equal nearest accepted')
    except ValueError:
        pass
    pipe.dataProvider().deleteFeatures([other])
    # Selected null only: no zero fabrication, warning in preview.
    depth.selectByIds([ids[0]])
    empty = Spatial(pipe).aggregate(geom, dict(params, scope='selected'))
    assert empty['mean'] is None and empty['excluded'] == 1
    depth.selectByIds([ids[3]])
    assert Spatial(pipe).aggregate(geom, dict(params, scope='selected'))['mean'] == 5
    depth.removeSelection()
    # Rounded overflow displayed before execution and no output added.
    overflow = deepcopy(profile)
    overflow['field_rules']['mean'].update(operation='CONSTANT', params=dict(value='999.995'))
    window.raw_profile = overflow
    window.prepare()
    assert window.object_table.item(0, 0).background().color().name() == '#ffd6d6'
    window.error_only.setChecked(True)
    assert window.object_table.rowCount() == 1
    before = set(project.mapLayers())
    try:
        window.execute()
        raise AssertionError('Overflow accepted')
    except ValueError:
        pass
    assert set(project.mapLayers()) == before
    window.error_only.setChecked(False)
    assert pipe_before == [(f.id(), f.attributes(), bytes(f.geometry().asWkb())) for f in pipe.getFeatures()]
    # Native GDAL Excel support: columns remain explicit text, including leading zeroes.
    from osgeo import ogr, gdal
    from geoflow_qc_structure.references import import_rows
    with TemporaryDirectory() as directory:
        path = str(Path(directory) / 'codes.xlsx')
        ds = ogr.GetDriverByName('XLSX').CreateDataSource(path)
        sheet = ds.CreateLayer('Codes', geom_type=ogr.wkbNone)
        for name in ['label', 'aliases', 'output', 'meaning']:
            sheet.CreateField(ogr.FieldDefn(name, ogr.OFTString))
        f = ogr.Feature(sheet.GetLayerDefn())
        for i, value in enumerate(['Name', '["PE", "Poly"]', '001', 'material.pe']):
            f.SetField(i, value)
        assert sheet.CreateFeature(f) == 0
        f, sheet, ds = None, None, None
        ds = gdal.OpenEx(path, gdal.OF_VECTOR, open_options=['HEADERS=FORCE', 'FIELD_TYPES=STRING'])
        sheet = ds.GetLayerByName('Codes')
        entries = import_rows([[f.GetField(i) for i in range(4)] for f in sheet], dict(code=2, name=0, meaning=3, aliases=1))
        assert entries[0]['code'] == '001'
        sheet, ds = None, None
        from geoflow_qc_structure.reference_editor import ReferenceEditor
        editor = ReferenceEditor(window, directory)
        for key, value in dict(id='test_material', agency='A', business='water', kind='material', mapping_id='survey').items():
            editor.controls[key].setText(value)
        editor.populate(entries)
        editor.save()
        assert len(editor.store.revisions()) == 1
        first = editor.store.revisions()[0]
        from geoflow_qc_structure.operation_editor import ReferenceSettings
        settings = ReferenceSettings(window, dict(book=first), directory)
        configured = settings.parameters('code')
        assert configured['unregistered'] == 'error' and configured['book']['revision'] == 1
        editor.grid.item(0, 0).setText('002')
        editor.save()
        assert [b['revision'] for b in editor.store.revisions()] == [1, 2]
    window.raw_profile = profile
    window.prepare()
    window.tabs.setCurrentIndex(2)
    window.resize(1200, 800)
    window.show()
    from qgis.core import QgsApplication
    QgsApplication.processEvents()
    artifact = os.environ.get('GEOFLOW_QGIS_QC_RESULT')
    if artifact:
        window.object_table.setCurrentCell(0, 0)
        window.grab().save(str(Path(artifact).with_suffix('.png')))
    print('PASS: object/cell preview, exact output, reference invalidation, stored numeric aggregate, null/zero/negative, ambiguity, overflow, Excel')
finally:
    for layer in owned:
        project.removeMapLayer(layer.id())
    window.invalidate()
