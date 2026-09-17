# 제목: forms/common/values.py
# 기능: QGIS NULL 값을 공통 Python 값으로 정규화
from qgis.core import QgsVariantUtils


def clean(value):
    return None if value is None or QgsVariantUtils.isNull(value) else value
