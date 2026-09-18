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
from qgis.core import QgsVectorLayer, QgsFeature
from qgis.gui import QgsMapToolIdentify, QgsMapMouseEvent

# ============================================================
# 지도 객체 선택과 속성폼 연결
# ============================================================
class IdentifyGeometry(QgsMapToolIdentify):
    # signal definition
    geomIdentified = pyqtSignal(QgsVectorLayer, QgsFeature, QgsMapMouseEvent)

    def __init__(self, canvas, layerType = 'AllLayers', layer_provider=None):
        self.layer_provider = layer_provider
        self.layerType = getattr(QgsMapToolIdentify, layerType)
        self.canvas = canvas
        QgsMapToolIdentify.__init__(self, canvas)
        self.setCursor(QCursor())

    def canvasReleaseEvent(self, mouseEvent):
        try:
            pos = mouseEvent.pos()
            if self.layer_provider is not None:
                managed = self.layer_provider()
                layers = [layer for layer in self.canvas.layers() if managed.get(layer.id()) is layer]
                # QGIS interprets an empty layerList as all layers: never pass it.
                results = self.identify(pos.x(), pos.y(), layers, QgsMapToolIdentify.TopDownStopAtFirst) if layers else []
            else:
                results = self.identify(pos.x(), pos.y(), QgsMapToolIdentify.ActiveLayer, self.layerType)
        except Exception as e:
            print ("Identify  EXCEPTION: ", e)
            results = []

        if len(results) > 0:
            self.geomIdentified.emit(results[0].mLayer, QgsFeature(results[0].mFeature), mouseEvent)
        else:
            self.canvas.refresh()
