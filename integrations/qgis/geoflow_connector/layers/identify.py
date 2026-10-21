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
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QPixmap, QCursor
from qgis.core import QgsVectorLayer, QgsFeature, QgsMessageLog
from qgis.gui import QgsMapToolIdentify, QgsMapMouseEvent

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

    def canvasReleaseEvent(self, mouseEvent):
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
            results = []

        if len(results) > 0:
            self.geomIdentified.emit(results[0].mLayer, QgsFeature(results[0].mFeature), mouseEvent)
        else:
            self.noFeatureIdentified.emit()
            self.canvas.refresh()
