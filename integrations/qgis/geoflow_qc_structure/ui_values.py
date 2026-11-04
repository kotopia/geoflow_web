from decimal import Decimal
from datetime import date, datetime

from qgis.PyQt.QtCore import QDate, QDateTime, QMetaType
from qgis.core import QgsField, QgsVariantUtils


def scalar(value):
    if QgsVariantUtils.isNull(value):
        return None
    if isinstance(value, QDateTime):
        return value.toPyDateTime()
    if isinstance(value, QDate):
        return value.toPyDate()
    return value


def output_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return QDateTime(value)
    if isinstance(value, date):
        return QDate(value.year, value.month, value.day)
    return value


def qgis_field(field):
    T = QMetaType.Type
    types = {"SMALLINT":T.Int, "INTEGER":T.Int, "BIGINT":T.LongLong,
             "REAL":T.Double, "DOUBLE":T.Double, "NUMERIC":T.Double, "DECIMAL":T.Double,
             "BOOLEAN":T.Bool, "DATE":T.QDate, "DATETIME":T.QDateTime, "TIMESTAMP":T.QDateTime}
    kind = field["data_type"]
    return QgsField(field["physical_name"], types.get(kind,T.QString), kind,
                    field.get("length", field.get("precision", 0)), field.get("scale",0))
