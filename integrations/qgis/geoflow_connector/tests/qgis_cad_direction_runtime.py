"""Disposable QGIS/Qt acceptance checks; never opens operational layers/settings."""
import copy
import math
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from qgis.core import *
from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtWidgets import QMainWindow
from qgis.gui import QgsMapCanvas
APP = QgsApplication.instance() or QgsApplication([], False)
getattr(__import__('qgis.utils',fromlist=['iface']),'iface',None) or QgsApplication.initQgis()
TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, TMP.name)
from geoflow_connector.services.direction import DirectionService
from geoflow_connector.services.direction_math import *
from geoflow_connector.ui.direction import DirectionResults, RotationTool, CadDial
from geoflow_connector.ui.settings_dialog import GeoFlowSettingsDialog

project = QgsProject.instance()
project.clear()
project.setCrs(QgsCoordinateReferenceSystem(ANGLE_CRS))
window = QMainWindow()
canvas = QgsMapCanvas()
canvas.setDestinationCrs(project.crs())
canvas.resize(700, 500)
points = QgsVectorLayer('Point?crs=EPSG:5186&field=id:string&field=angle:double', 'Facilities', 'memory')
lines = QgsVectorLayer('MultiLineString?crs=EPSG:5186&field=id:string', 'Pipes', 'memory')
p_id, l_id, f_id = [str(uuid4()) for _ in range(3)]
for layer, key in ((points, p_id), (lines, l_id)):
    layer.setCustomProperty('geoflow/definition_layer_id', key)
    project.addMapLayer(layer)
config = dict(reference_layer_ids=[l_id], method='nearest', distance=.2, unit='m',
    offset=0, allow_reverse=True, ambiguity='review', zero_axis='east',
    positive_direction='counterclockwise', symbol_offset=0, axis_tolerance=1, tie_tolerance=.001)
field = dict(id=f_id, layer_id=p_id, storage=dict(kind='column', key='angle'),
    semantic_data_type='decimal', scale=3, readonly=False, direction=copy.deepcopy(config))
plugin = SimpleNamespace(active_context={'project_id':'cad-test'},
    _definition_service=SimpleNamespace(definition={'fields':[field]}, client=SimpleNamespace(base_url='https://example.invalid')),
    _managed_layers=lambda:[points,lines], iface=SimpleNamespace(mainWindow=lambda:window),
    mapCanvas=canvas, work=SimpleNamespace(pages={}), edit_tools=None,
    integration_state=lambda:{'ready':True,'can_write':True})
service = DirectionService(plugin)
controller = SimpleNamespace(plugin=plugin, direction=service)
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtCore import QPoint
dial = CadDial(); dial.setRange(0,35999); dial.setWrapping(True); dial.resize(160,160); dial.show()
APP.processEvents()
center=dial.rect().center()
for dx,dy,expected in ((50,0,0),(0,-50,9000),(-50,0,18000),(0,50,27000)):
    QTest.mouseClick(dial,Qt.MouseButton.LeftButton,pos=center+QPoint(dx,dy))
    assert dial.value()==expected,(dx,dy,dial.value())
dial.close()

def add(layer, geometry, angle=None):
    feature = QgsFeature(layer.fields())
    feature['id'] = str(uuid4())
    if 'angle' in layer.fields().names(): feature['angle'] = angle
    feature.setGeometry(QgsGeometry.fromWkt(geometry))
    ok, added = layer.dataProvider().addFeatures([feature])
    assert ok
    return added[0]

def clear_lines():
    lines.dataProvider().deleteFeatures(list(lines.allFeatureIds()))

point = add(points, 'POINT(200000 600000)', 12.345)
canvas.setExtent(QgsRectangle(199980,599980,200020,600020))
canvas.setLayers([points,lines])
for expected in range(0,360,45):
    dx, dy = 10*math.cos(math.radians(expected)), 10*math.sin(math.radians(expected))
    clear_lines()
    add(lines, f'MULTILINESTRING((200000 600000,{200000+dx} {600000+dy}))')
    result = service.inspect(points, point)
    assert result['status']=='ok', result
    assert min(abs(result['angle']-expected),360-abs(result['angle']-expected))<1e-6, result
    # Endpoint preserves original order, and reversing geometry changes 180 degrees.
    endpoint = QgsFeature(point); endpoint.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(200000+dx,600000+dy)))
    end_result = service.inspect(points,endpoint)
    assert min(abs(end_result['angle']-expected),360-abs(end_result['angle']-expected))<1e-6,(expected,end_result)
    clear_lines(); add(lines,f'MULTILINESTRING(({200000+dx} {600000+dy},200000 600000))')
    reversed_result=service.inspect(points,point)
    assert abs(normalize(reversed_result['angle']-result['angle'])-180)<1e-6

# Actual nearby part, duplicates, no reference, zero length, and interior bends.
for wkt, status, angle in [
 ('MULTILINESTRING((200100 600100,200110 600100),(199990 600000,200000 600000,200000 600000,200010 600000))','ok',0),
 ('MULTILINESTRING((199990 600000,200000 600000,200000 600010))','ambiguous',None),
 ('MULTILINESTRING((199990 600000,200000 600000,199990 600000))','ambiguous',None),
 ('MULTILINESTRING((200000 600000,200000 600000))','no_reference',None),
 ('MULTILINESTRING((200100 600100,200110 600100))','no_reference',None),
]:
    clear_lines();add(lines,wkt);r=service.inspect(points,point)
    assert r['status']==status,r
    if angle is not None: assert min(r['angle'],360-r['angle'])<1e-6,r

clear_lines()
add(lines,'MULTILINESTRING((199990 600000,200010 600000),(200000 599990,200000 600010))')
single=DirectionResults(controller,points,[point]);assert len(single.rows)==2
assert all(single.table.item(i,0).flags() & Qt.ItemFlag.ItemIsUserCheckable for i in range(2))
second=add(points,'POINT(200000 600000)',20)
batch=DirectionResults(controller,points,[point,second]);assert len(batch.rows)==2
assert all(not batch.table.item(i,0).flags() & Qt.ItemFlag.ItemIsUserCheckable for i in range(2))
single.reject();batch.reject()

# HALF_UP happens after conversion, with wrap after rounding. No inspect rounding.
for value, precision, expected in [(359.5,0,0),(89.5,0,90),(90.5,0,91),(-.0005,3,0),(359.9995,3,0),(12.3455,3,12.346)]:
    assert quantize_angle(value,precision)==expected
for a in (0,45,90,135,180,225,270,315):
    assert to_storage(a,config)==normalize(90-a)
    assert quantize_angle(to_storage(a,config),0)==normalize(90-round(a))
assert quantize_angle(to_storage(90.5,config),0)==0
assert normalize(90-round(90.5))==0  # common float ties-to-even legacy case
assert quantize_angle(to_storage(89.5,config),0)==1
assert normalize(90-round(89.5))==0  # documented legacy/new tie difference
integer_layer=QgsVectorLayer('Point?crs=EPSG:5186&field=angle:integer','Actual integer','memory')
assert service.storage_value(integer_layer,field,359.5)==0
assert service.storage_value(integer_layer,field,12.5)==13
from qgis.PyQt.QtCore import QMetaType
precision_layer=QgsVectorLayer('Point?crs=EPSG:5186','Actual precision','memory')
precision_layer.dataProvider().addAttributes([QgsField('angle',QMetaType.Type.Double,'double',10,2)])
precision_layer.updateFields()
assert service.storage_value(precision_layer,field,12.345)==12.35
field['scale']=0
manual=service.manual_result(points,point)
applied=service.apply(points,[dict(manual,angle=359.5)],track=False)
assert applied[0]['angle']==0 and points.getFeature(point.id())['angle']==0
points.undoStack().undo();assert points.getFeature(point.id())['angle']==12.345
points.rollBack();field['scale']=3

# Fixed operational convention even with old preferences/central rules.
field['direction'].update(zero_axis='north',positive_direction='clockwise')
assert service.settings(points)[1]['zero_axis']=='east'
assert service.settings(points)[1]['positive_direction']=='counterclockwise'
dialog=GeoFlowSettingsDialog(plugin)
assert dialog.directionZeroCombo.currentData()=='east' and not dialog.directionZeroCombo.isEnabled()
assert dialog.directionPositiveCombo.currentData()=='counterclockwise'
dialog.reject()

# Render expression + compound marker offsets are stable across repeated binding.
symbol=QgsMarkerSymbol.createSimple({'name':'arrow','angle':'0'})
symbol.appendSymbolLayer(QgsSimpleMarkerSymbolLayer.create({'name':'triangle','angle':'30'}))
points.renderer().setSymbol(symbol)
def evaluated(layer, angle, dest='EPSG:5186'):
    maps=QgsMapSettings();maps.setDestinationCrs(QgsCoordinateReferenceSystem(dest));maps.setLayers([layer])
    context=QgsExpressionContext();context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    context.appendScope(QgsExpressionContextUtils.mapSettingsScope(maps))
    f=QgsFeature(next(layer.getFeatures()));f['angle']=angle;context.setFeature(f)
    s=layer.renderer().symbol()
    return [sl.dataDefinedProperties().property(QgsSymbolLayer.Property.Angle).valueAsDouble(context)[0] for sl in s.symbolLayers()]
service.bind_renderer(points)
for angle in range(0,360,45):
    vals=evaluated(points,angle)
    assert abs(normalize(vals[0])-normalize(90-angle))<1e-6,(angle,vals)
    assert abs(normalize(vals[1]-vals[0])-30)<1e-6,vals
service.bind_renderer(points)
assert abs(normalize(evaluated(points,25)[1]-evaluated(points,25)[0])-30)<1e-6

# Handle direction uses CAD axes even on a different projected map canvas.
canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3857'))
canvas.setExtent(QgsCoordinateTransform(project.crs(),canvas.mapSettings().destinationCrs(),project).transformBoundingBox(QgsRectangle(199980,599980,200020,600020)))
tool=RotationTool(canvas,points,point,service.settings(points,manual=True)[1],lambda value:None)
for angle in range(0,360,45):
    tool.preview(angle)
    p=tool.map_to_cad.transform(tool.end)
    actual=to_storage(bearing((tool.cad_center.x(),tool.cad_center.y()),(p.x(),p.y())),config)
    assert min(abs(actual-angle),360-abs(actual-angle))<.001,(angle,actual)
    expected=to_bearing(actual,config)
    visual=bearing((tool.center.x(),tool.center.y()),(tool.end.x(),tool.end.y()))
    assert abs(normalize(evaluated(points,angle,'EPSG:3857')[0])-visual)<.001
tool.dispose()

# Render a disposable, explicitly north-pointing triangle through the real renderer.
visual=QgsVectorLayer('Point?crs=EPSG:5186&field=angle:double','CAD 8 directions','memory')
visual.setCustomProperty('geoflow/definition_layer_id',p_id)
visual.renderer().setSymbol(QgsMarkerSymbol.createSimple({'name':'triangle','angle':'0','size':'10','color':'20,110,210'}))
for index,angle in enumerate(range(0,360,45)):
    f=QgsFeature(visual.fields());f['angle']=angle
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(200000+(index%4)*20,600020-(index//4)*20)))
    visual.dataProvider().addFeatures([f])
service.bind_renderer(visual)
from qgis.PyQt.QtCore import QSize
settings=QgsMapSettings();settings.setDestinationCrs(project.crs());settings.setLayers([visual])
settings.setOutputSize(QSize(800,400));settings.setExtent(QgsRectangle(199990,599990,200070,600030))
job=QgsMapRendererParallelJob(settings);job.start();job.waitForFinished()
image=job.renderedImage()
from qgis.PyQt.QtGui import QPainter, QColor, QFont, QFontDatabase
if Path('C:/Windows/Fonts/arial.ttf').exists():
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
painter=QPainter(image);painter.setPen(QColor('black'))
painter.setFont(QFont('Arial',12))
for index,angle in enumerate(range(0,360,45)):
    painter.drawText(80+(index%4)*200,165+(index//4)*200,str(angle)+' degrees')
painter.end()
import configparser
meta=configparser.ConfigParser();meta.read(Path(__file__).resolve().parents[1]/'metadata.txt')
out=Path(__file__).resolve().parents[1]/'release'/meta['general']['version'];out.mkdir(parents=True,exist_ok=True)
assert image.save(str(out/'cad-directions.png'))

# Durable file values + renderer survive actual project reload (no operational write).
options=QgsVectorFileWriter.SaveVectorOptions();options.driverName='GPKG'
gpkg=str(Path(TMP.name)/'test.gpkg')
assert QgsVectorFileWriter.writeAsVectorFormatV3(points,gpkg,project.transformContext(),options)[0]==QgsVectorFileWriter.NoError
persisted=QgsVectorLayer(gpkg,'Persisted','ogr');persisted.setRenderer(points.renderer().clone());project.addMapLayer(persisted)
assert next(persisted.getFeatures())['angle']==12.345
project.removeMapLayer(points.id());project.removeMapLayer(lines.id())
qgz=str(Path(TMP.name)/'test.qgz');assert project.write(qgz)
project.clear();assert project.read(qgz)
reloaded=next(iter(project.mapLayers().values()))
assert next(reloaded.getFeatures())['angle']==12.345
assert abs(evaluated(reloaded,90)[0])<1e-6
project.clear();canvas.setLayers([]);window.close()
print('CAD_QGIS_OK: cardinals/diagonals/endpoints/reversal/multipart/duplicates/ambiguity/rounding/settings/symbols/handle/project-reload; operational data untouched')
