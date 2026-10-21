"""One CRS-safe nearby search engine; all public distances are metres."""
from __future__ import annotations

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDistanceArea,
    QgsGeometry, QgsPointXY, QgsProject,
)


def within_radius(distance_m, radius_m):
    """Include the metric boundary despite sub-micrometre transform rounding."""
    return distance_m <= radius_m + 1e-6


class NearbySearchService:
    def __init__(self, project=None, logger=None):
        self.project = project or QgsProject.instance()
        self.logger = logger

    @staticmethod
    def _point(geometry: QgsGeometry):
        if geometry is None or geometry.isNull() or geometry.isEmpty():
            return None
        point = geometry.asPoint() if geometry.type().name == "Point" else geometry.pointOnSurface().asPoint()
        return QgsPointXY(point)

    def _wgs84_point(self, geometry, source_crs):
        point = self._point(geometry)
        if point is None or source_crs is None or not source_crs.isValid():
            return None
        target = QgsCoordinateReferenceSystem("EPSG:4326")
        if source_crs != target:
            point = QgsCoordinateTransform(
                source_crs, target, self.project.transformContext()
            ).transform(point)
        return point

    def find_nearby(
        self, source_geometry, source_crs, target_layer, radius,
        *, predicate=None, limit=1, nearest_first=True, function="nearby",
    ):
        try:
            radius = float(radius)
        except (TypeError, ValueError):
            return []
        self._log(function, radius_m=radius, source_layer=self._layer_name(target_layer))
        origin = self._wgs84_point(source_geometry, source_crs)
        if origin is None or target_layer is None or radius < 0:
            return []
        distance = QgsDistanceArea()
        distance.setSourceCrs(QgsCoordinateReferenceSystem("EPSG:4326"), self.project.transformContext())
        ellipsoid = str(self.project.ellipsoid() or "").strip()
        distance.setEllipsoid(
            "WGS84" if not ellipsoid or ellipsoid.upper() == "NONE" else ellipsoid
        )
        matches = []
        for feature in target_layer.getFeatures():
            if predicate is not None and not predicate(feature):
                continue
            candidate = self._wgs84_point(feature.geometry(), target_layer.crs())
            if candidate is None:
                continue
            metres = float(distance.measureLine(origin, candidate))
            if within_radius(metres, radius):
                matches.append({
                    "feature": feature,
                    "distance_m": metres,
                    # Compatibility with the initial local prototype.
                    "distance": metres,
                })
        if nearest_first:
            matches.sort(key=lambda row: (row["distance_m"], row["feature"].id()))
        selected = matches[:max(0, int(limit))]
        self._log(
            function, candidate_count=len(matches),
            selected_distance=(selected[0]["distance_m"] if selected else None),
        )
        return selected

    def find_nearest(
        self, target_geometry, source_layer, radius_m, filter_fn=None, *,
        target_crs=None, candidate_limit=1, nearest_first=True,
        function="nearby",
    ):
        """Return compatible result rows, nearest first by default."""
        return self.find_nearby(
            target_geometry, target_crs or source_layer.crs(), source_layer,
            radius_m, predicate=filter_fn, limit=candidate_limit,
            nearest_first=nearest_first, function=function,
        )

    @staticmethod
    def _layer_name(layer):
        if layer is None:
            return ""
        standard = str(layer.customProperty("geoflow/standard_name", "") or "")
        return standard or layer.name()

    def _log(self, function, **values):
        if not callable(self.logger):
            return
        self.logger(f"[NEARBY] function={function}")
        for key, value in values.items():
            self.logger(f"[NEARBY] {key}={value}")


# Import compatibility for existing extensions and runtime checks.
NearbyService = NearbySearchService


class NearbyStrategyRegistry:
    def __init__(self):
        self._strategies = {}

    def register(self, standard_name, strategy):
        self._strategies.setdefault(str(standard_name).upper(), []).append(strategy)

    def for_layer(self, standard_name):
        return tuple(self._strategies.get(str(standard_name).upper(), ()))
