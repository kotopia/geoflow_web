"""Run in an isolated QGIS 4.2.2 profile Python console with both ZIPs installed.

exec(open('/absolute/path/scripts/qgis/qc_structure_runtime.py', encoding='utf-8').read())
Uses only memory layers. The launcher rejects non-test profiles.
"""
from qgis.core import Qgis, QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.utils import iface, plugins
from pathlib import Path

assert Qgis.QGIS_VERSION.startswith("4.2.2"), Qgis.QGIS_VERSION
assert Path(QgsApplication.qgisSettingsDirPath()).name.startswith("qc_structure_test")
assert "geoflow_connector" in plugins and "geoflow_qc_structure" in plugins
plugin = plugins["geoflow_qc_structure"]
project = QgsProject.instance()
layer = QgsVectorLayer("LineString?crs=EPSG:5186&field=pip_len:double", "QC pilot fixture", "memory")
ref = QgsVectorLayer("Point?crs=EPSG:5186&field=ref:string", "QC reference fixture", "memory")
layers = [layer, ref]
for lyr, wkt, value in [(layer, "LINESTRING (200000 500000, 200010 500000)", 12.34),
                        (ref, "POINT (200000 500000)", "START"),
                        (ref, "POINT (200010 500000)", "END")]:
    feature = QgsFeature(lyr.fields())
    feature.setAttributes([value])
    feature.setGeometry(QgsGeometry.fromWkt(wkt))
    assert lyr.dataProvider().addFeatures([feature])[0]
for lyr in layers:
    lyr.updateExtents()
    project.addMapLayer(lyr)
try:
    before = {f.id():(list(f.attributes()), bytes(f.geometry().asWkb())) for f in layer.getFeatures()}
    iface.setActiveLayer(layer)
    plugin.show()
    window = plugin.window
    assert window.isVisible() and not window.isModal()
    window.layers.setCurrentIndex(window.layers.findData(layer.id()))
    window.profiles.setCurrentIndex(window.profiles.findData("DAEJEON_WATER_PIPE_PILOT"))
    spatial = window.context()[3]
    geom = next(layer.getFeatures()).geometry()
    params = dict(reference_layer=ref.id(), reference_field="ref", crs="EPSG:5186", radius=0.05)
    assert spatial.lookup(geom,params,"START_REFERENCE") == "START"
    assert spatial.lookup(geom,params,"END_REFERENCE") == "END"
    assert spatial.measure(geom,dict(crs="EPSG:5186",unit="m"),"LENGTH") == 10
    assert spatial.measure(geom,dict(crs="EPSG:5186"),"ANGLE") == 0
    window.scan()
    assert not window.findings
    window.prepare()
    assert window.preview_state is not None
    ids = set(project.mapLayers())
    window.execute()
    added = set(project.mapLayers()) - ids
    assert len(added) == 1
    result = project.mapLayer(added.pop())
    layers.append(result)
    output = next(result.getFeatures())
    assert output["BYC_LEN"] == 12.34 and output["ftr_cde"] == "SA001" and output["mng_cde"] == "MNG002"
    assert before == {f.id():(list(f.attributes()), bytes(f.geometry().asWkb())) for f in layer.getFeatures()}
    print("PASS: both plugins enabled; spatial lookup, QC, preview, memory output, source preservation")
finally:
    plugin.window.close()
    for lyr in layers:
        project.removeMapLayer(lyr.id())
