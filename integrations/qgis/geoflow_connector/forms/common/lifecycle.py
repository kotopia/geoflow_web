# 제목: forms/common/lifecycle.py
# 기능: 업무폼 소유 기간의 기본 팝업 억제와 신규 객체 단독 버퍼 검사
"""Scoped QGIS form settings and safe single-feature edit-buffer checks."""
from qgis.core import Qgis
from qgis.PyQt import sip


class BusinessFormSettings:
    """Suppress native creation dialogs only while supported business UI owns them."""
    def __init__(self):
        self.previous = {}

    def update(self, layers, standards):
        desired = {key: layer for key, layer in layers.items()
                   if str(layer.customProperty('geoflow/standard_name', '')) in standards
                   and not layer.readOnly()}
        for key in list(self.previous):
            if key not in desired or self.previous[key][0] is not desired[key]:
                self.restore(key)
        for key, layer in desired.items():
            if key not in self.previous:
                config = layer.editFormConfig()
                self.previous[key] = (layer, config.suppress())
                config.setSuppress(Qgis.AttributeFormSuppression.On)
                layer.setEditFormConfig(config)

    def restore(self, key):
        layer, previous = self.previous.pop(key)
        if not sip.isdeleted(layer):
            config = layer.editFormConfig()
            if config.suppress() == Qgis.AttributeFormSuppression.On:
                config.setSuppress(previous)
                layer.setEditFormConfig(config)

    def close(self):
        for key in list(self.previous):
            self.restore(key)


def sole_new_feature(layer, fid):
    """Never commit unrelated edits with a business-form save."""
    buffer = layer.editBuffer()
    if buffer is None or set(buffer.addedFeatures()) != {fid}:
        return False
    return (not buffer.deletedFeatureIds() and not buffer.addedAttributes()
            and not buffer.deletedAttributeIds()
            and set(buffer.changedAttributeValues()).issubset({fid})
            and set(buffer.changedGeometries()).issubset({fid}))
