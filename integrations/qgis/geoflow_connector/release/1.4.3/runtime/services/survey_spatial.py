"""Project-scoped spatial matching without persistent Survey relationships."""
from qgis.core import QgsCoordinateReferenceSystem, QgsGeometry, QgsPointXY, QgsDistanceArea, QgsProject

from .nearby import NearbySearchService, within_radius
from .settings import GeoFlowSettingsService


def value(feature, name):
    names = {key.casefold(): key for key in feature.fields().names()}
    key = names.get(name.casefold())
    result = feature[key] if key else None
    try:
        return None if result.isNull() else result
    except AttributeError:
        return result


def active_feature(feature, project_id):
    project = value(feature, 'project_id')
    if project not in (None, '') and str(project).strip('{}') != str(project_id).strip('{}'):
        return False
    if value(feature, 'is_deleted') in (True, 1, 'true', 'True'):
        return False
    if value(feature, 'deleted_at') not in (None, ''):
        return False
    geometry = feature.geometry()
    return not geometry.isNull() and not geometry.isEmpty()


def point_geometry(point):
    return QgsGeometry.fromPointXY(QgsPointXY(
        float(point['longitude']), float(point['latitude'])
    ))


def nearby_targets(plugin, point, layer, code):
    project_id = (plugin.active_context or {}).get('project_id', '')
    return NearbySearchService().find_nearby(
        point_geometry(point), QgsCoordinateReferenceSystem('EPSG:4326'),
        layer, GeoFlowSettingsService(plugin).get_default_nearby_radius(),
        predicate=lambda row: active_feature(row, project_id)
        and str(value(row, 'ftr_cde') or '') == str(code),
        function='survey_creation',
    )


def points_overlap(plugin, first, second):
    distance = QgsDistanceArea()
    distance.setSourceCrs(QgsCoordinateReferenceSystem('EPSG:4326'),
                          QgsProject.instance().transformContext())
    distance.setEllipsoid('WGS84')
    return within_radius(distance.measureLine(point_geometry(first).asPoint(),
                                              point_geometry(second).asPoint()),
                         GeoFlowSettingsService(plugin).get_default_nearby_radius())
