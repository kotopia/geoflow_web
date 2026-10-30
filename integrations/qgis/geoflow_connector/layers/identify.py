# -*- coding: utf-8 -*-
# 제목: layers/identify.py
# 기능: 현재 관리 레이어의 지도 객체 식별 map tool
"""
/***************************************************************************
 Water Quick Edit Attribute
                                 A QGIS plugin
 tool for quick editing attributes in field campaigns
                             -------------------
        begin                : 2020-05-31
        copyright            : (C) 2020 by Zhefeng Jin
        email                : wugis1219@gmail.com
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from qgis.PyQt.QtCore import pyqtSignal, Qt, QPoint
from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt.QtGui import QPixmap, QCursor, QColor
from qgis.core import QgsVectorLayer, QgsFeature, QgsMessageLog, QgsGeometry, QgsPointXY, QgsFeatureRequest, QgsCoordinateTransform, QgsProject, QgsWkbTypes
from qgis.gui import QgsMapToolIdentify, QgsMapMouseEvent, QgsRubberBand

# ============================================================
# 지도 객체 선택과 속성폼 연결
# ============================================================
class IdentifyGeometry(QgsMapToolIdentify):
    # signal definition
    geomIdentified = pyqtSignal(QgsVectorLayer, QgsFeature, QgsMapMouseEvent)
    noFeatureIdentified = pyqtSignal()

    def __init__(self, canvas, layerType = 'AllLayers', layer_provider=None, active_layer=None, notify=None):
        self.layer_provider = layer_provider
        self.active_layer = active_layer or canvas.currentLayer
        self.notify = notify
        self.layerType = getattr(QgsMapToolIdentify, layerType)
        self.canvas = canvas
        QgsMapToolIdentify.__init__(self, canvas)
        self.setCursor(QCursor())
        self._start = None
        self._drag_layer = None
        self._band = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.PolygonGeometry)
        self._band.setColor(QColor(40, 120, 220, 70))
        self._band.setWidth(1)

    def cancel_drag(self, *args):
        self._start = self._drag_layer = None
        self._band.reset(QgsWkbTypes.GeometryType.PolygonGeometry)

    def deactivate(self):
        self.cancel_drag()
        super().deactivate()

    def dispose(self):
        self.cancel_drag()
        self.canvas.scene().removeItem(self._band)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_drag()
        else:
            super().keyPressEvent(event)

    def canvasPressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.cancel_drag()
            self._start = event.pos()
            self._drag_layer = self.active_layer()

    def _rectangle(self, end):
        a, b = self._start, end
        points = [self.toMapCoordinates(QPoint(x, y)) for x, y in (
            (a.x(), a.y()), (b.x(), a.y()), (b.x(), b.y()), (a.x(), b.y()), (a.x(), a.y()))]
        return QgsGeometry.fromPolygonXY([points])

    def canvasMoveEvent(self, event):
        if self._start is not None:
            self._band.setToGeometry(self._rectangle(event.pos()), None)

    @staticmethod
    def select_ids(layer, ids, modifiers):
        current = set(layer.selectedFeatureIds())
        ids = set(ids)
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            ids = current - ids
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            ids |= current
        layer.selectByIds(sorted(ids))

    def _select_area(self, event):
        try:
            layer = self.active_layer()
            managed = self.layer_provider() if self.layer_provider else {}
            if self._start is None or layer is None or layer is not self._drag_layer or managed.get(layer.id()) is not layer:
                return
            polygon = self._rectangle(event.pos())
            # Transform the actual canvas polygon, not just its bounding box.
            polygon = polygon.densifyByCount(16)
            polygon.transform(QgsCoordinateTransform(
                self.canvas.mapSettings().destinationCrs(), layer.crs(), QgsProject.instance()))
            request = QgsFeatureRequest().setFilterRect(polygon.boundingBox())
            ids = [f.id() for f in layer.getFeatures(request)
                   if f.hasGeometry() and polygon.intersects(f.geometry())]
            self.select_ids(layer, ids, event.modifiers())
        except Exception as exc:
            if self.notify:
                self.notify('영역 선택 실패: ' + str(exc))
        finally:
            self.cancel_drag()


    def canvasReleaseEvent(self, mouseEvent):
        if mouseEvent.button() != Qt.MouseButton.LeftButton:
            return
        if self._start is None:
            return
        dragged = (mouseEvent.pos() - self._start).manhattanLength() >= QApplication.startDragDistance()
        if dragged:
            self._select_area(mouseEvent)
            return
        self.cancel_drag()
        try:
            pos = mouseEvent.pos()
            layer = self.active_layer()
            managed = self.layer_provider() if self.layer_provider else {}
            if not isinstance(layer, QgsVectorLayer) or managed.get(layer.id()) is not layer:
                if self.notify:
                    self.notify('선택할 GeoFlow 관리 레이어를 먼저 선택하세요.')
                QgsMessageLog.logMessage('[FEATURE_SELECT] active_layer=unavailable candidate_count=0 selected_feature_id=', 'GeoFlow')
                return
            # Never pass an empty list: QGIS interprets it as all layers.
            results = self.identify(pos.x(), pos.y(), [layer], QgsMapToolIdentify.TopDownAll)
            QgsMessageLog.logMessage(
                f'[FEATURE_SELECT] active_layer={layer.id()} candidate_count={len(results)} '
                f'selected_feature_id={results[0].mFeature.id() if results else ""}', 'GeoFlow')
        except Exception as e:
            print ("Identify  EXCEPTION: ", e)
            return

        if mouseEvent.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
            self.select_ids(layer, [results[0].mFeature.id()] if results else [], mouseEvent.modifiers())
            return
        if len(results) > 0:
            self.geomIdentified.emit(results[0].mLayer, QgsFeature(results[0].mFeature), mouseEvent)
        else:
            self.noFeatureIdentified.emit()
            self.canvas.refresh()
