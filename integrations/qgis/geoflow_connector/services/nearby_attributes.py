"""Shared nearby lookup entry point for future/central attribute-copy rules."""
from __future__ import annotations

from .nearby import NearbySearchService
from .settings import GeoFlowSettingsService


class NearbyAttributeService:
    """Find a source without inventing which attributes are safe to copy."""

    def __init__(self, plugin, *, settings=None, project=None):
        self.plugin = plugin
        self.settings = settings or GeoFlowSettingsService(plugin)
        self.search = NearbySearchService(project, logger=getattr(plugin, "log", None))

    def find_manhole_source(self, geometry, layer, *, geometry_crs=None,
                             filter_fn=None, limit=1):
        return self.search.find_nearest(
            geometry, layer, self.settings.get_manhole_radius(), filter_fn,
            target_crs=geometry_crs, candidate_limit=limit,
            nearest_first=self.settings.get_nearest_first(),
            function="manhole_attributes",
        )
