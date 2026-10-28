"""Render existing and explicitly connected styles using synthetic features only."""
import sys,json,hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from qgis.core import *
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QImage,QPainter,QColor,QFont,QFontDatabase
from geoflow_connector.services.direction import DirectionService
from geoflow_connector.layers.default_style import apply_default_qgis_style
APP=QgsApplication([],False);APP.initQgis()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
root=Path(__file__).resolve().parents[1]
out=root/'release'/'1.4.5';out.mkdir(parents=True,exist_ok=True)
report=[]; images=[]
for name in ('wtl_valv_ps','wtl_etc_ps'):
 layer=QgsVectorLayer('Point?crs=EPSG:3857&field=id:string&field=ang_dir:double&field=ftr_cde:string',name,'memory')
 apply_default_qgis_style(layer,name)
 layer.setLabelsEnabled(False)
 renderer=layer.renderer(); categories=renderer.rootRule().children()
 symbol_layers=[]
 for symbol in renderer.symbols(QgsRenderContext()):
  for sl in symbol.symbolLayers():
   prop=sl.dataDefinedProperties().property(QgsSymbolLayer.Property.PropertyAngle)
   symbol_layers.append(dict(type=sl.layerType(),base=sl.properties().get('angle'),
       marker=sl.properties().get('name'),active=prop.isActive(),expression=prop.expressionString(),field=prop.field()))
 # Prefer a visibly directional symbol, retaining the actual QML category.
 category=next((c for c in categories if any(sl.properties().get('name')=='filled_arrowhead' for sl in c.symbol().symbolLayers())),categories[0])
 category_label=category.label()
 layer.setRenderer(QgsSingleSymbolRenderer(category.symbol().clone()))
 f=QgsFeature(layer.fields());f['id']='synthetic';f['ftr_cde']=str(category_label);f['ang_dir']=0
 f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0,0)));layer.dataProvider().addFeature(f)
 def render(angle):
  layer.dataProvider().changeAttributeValues({f.id():{layer.fields().indexFromName('ang_dir'):angle}})
  settings=QgsMapSettings();settings.setLayers([layer]);settings.setDestinationCrs(layer.crs());settings.setExtent(QgsRectangle(-1,-1,1,1));settings.setOutputSize(QSize(240,200));settings.setOutputDpi(180);settings.setBackgroundColor(QColor('white'))
  job=QgsMapRendererParallelJob(settings);job.start();job.waitForFinished();return job.renderedImage()
 before=[render(0),render(90)]
 layer_id=str(uuid4());layer.setCustomProperty('geoflow/definition_layer_id',layer_id)
 cfg=dict(reference_layer_ids=[str(uuid4())],method='connected',distance=1,unit='m',offset=0,allow_reverse=True,ambiguity='review',zero_axis='north',positive_direction='clockwise',symbol_offset=90,axis_tolerance=1,tie_tolerance=0.01)
 definition={'fields':[dict(id=str(uuid4()),layer_id=layer_id,storage={'kind':'column','key':'ang_dir'},direction=cfg)]}
 service=DirectionService(SimpleNamespace(_definition_service=SimpleNamespace(definition=definition)))
 service.bind_renderer(layer)
 after=[render(0),render(90)]
 images.append((name,before+after))
 report.append(dict(layer=name,category=str(category_label),symbol_layers=symbol_layers,
                    before_0_equals_90=before[0]==before[1],after_0_equals_90=after[0]==after[1]))
 assert before[0]==before[1], 'Unexpected existing ang_dir connection; review convention'
 assert after[0]!=after[1], 'Explicit ang_dir connection did not rotate'
canvas=QImage(960,480,QImage.Format.Format_ARGB32);canvas.fill(QColor('white'));painter=QPainter(canvas);painter.setFont(QFont('Arial',11))
for row,(name,pictures) in enumerate(images):
 for col,picture in enumerate(pictures):
  painter.drawImage(col*240,row*240+30,picture)
  painter.drawText(col*240+10,row*240+22,name+' '+('existing' if col<2 else 'connected')+' '+str(90*(col%2)))
painter.end();canvas.save(str(out/'direction-style-audit.png'))
(out/'direction-style-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([{k:v for k,v in r.items() if k!='symbol_layers'} for r in report]))
