"""Temporary canvas feedback shared by inspection and calculation results."""
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsGeometry, QgsCoordinateTransform, QgsProject, QgsRectangle
from qgis.gui import QgsRubberBand

class ResultHighlight:
    COLORS = {'changed':'#16804a', 'failed':'#d32f2f', 'review':'#ed8b00', 'focus':'#1976d2'}
    def __init__(self, canvas):
        self.canvas, self.bands = canvas, []
    def clear(self):
        for band in self.bands:
            self.canvas.scene().removeItem(band)
        self.bands.clear()
    def add(self, geometry, crs, status='focus'):
        geom = QgsGeometry(geometry)
        if geom.isEmpty(): return None
        geom.transform(QgsCoordinateTransform(crs,self.canvas.mapSettings().destinationCrs(),QgsProject.instance()))
        band = QgsRubberBand(self.canvas,geom.type())
        band.setColor(QColor(self.COLORS.get(status,self.COLORS['review'])))
        band.setWidth(4); band.setIconSize(14); band.setToGeometry(geom,None)
        self.bands.append(band)
        return geom
    def show(self, layer, rows, *, zoom=False):
        self.clear(); geometries=[]
        for row in rows:
            feature=layer.getFeature(row['fid'])
            if feature.isValid():
                geom=self.add(feature.geometry(),layer.crs(),row.get('status','focus'))
                if geom is not None: geometries.append(geom)
        if zoom: self.zoom(geometries)
    def zoom(self, geometries):
        if not geometries: return
        bounds=QgsRectangle(geometries[0].boundingBox())
        for geom in geometries[1:]: bounds.combineExtentWith(geom.boundingBox())
        bounds.grow(max(self.canvas.mapUnitsPerPixel()*60,max(bounds.width(),bounds.height())*0.15))
        self.canvas.setExtent(bounds); self.canvas.refresh()
