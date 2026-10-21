"""Qt icon helper for GeoFlow's dedicated Tabler resource namespace."""

from qgis.PyQt.QtGui import QIcon


def tabler_icon(name):
    """Return an icon compiled under ``:/geoflow/tabler``."""
    return QIcon(f":/geoflow/tabler/{name}.svg")
