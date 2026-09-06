def classFactory(iface):
    from .cache_lifecycle_qgis import CacheLifecycleMixin
    from .delta_apply_v3 import DeltaApplyV3Mixin
    from .plugin import GeoFlowConnectorPlugin
    from .realtime_delta_v3 import RealtimeDeltaV3Mixin
    from .snapshot_reuse import SnapshotReuseMixin

    class GeoFlowConnectorPluginV071(
        CacheLifecycleMixin,
        RealtimeDeltaV3Mixin,
        SnapshotReuseMixin,
        DeltaApplyV3Mixin,
        GeoFlowConnectorPlugin,
    ):
        pass

    return GeoFlowConnectorPluginV071(iface)
