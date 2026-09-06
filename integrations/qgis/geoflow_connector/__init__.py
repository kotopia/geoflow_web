def classFactory(iface):
    from .cache_lifecycle_qgis import CacheLifecycleMixin
    from .delta_apply_v3 import DeltaApplyV3Mixin
    from .plugin import GeoFlowConnectorPlugin
    from .realtime_delta_v3 import RealtimeDeltaV3Mixin
    from .realtime_session_guard import RealtimeSessionGuardMixin
    from .snapshot_reuse import SnapshotReuseMixin

    class GeoFlowConnectorPluginV073(
        CacheLifecycleMixin,
        RealtimeSessionGuardMixin,
        RealtimeDeltaV3Mixin,
        SnapshotReuseMixin,
        DeltaApplyV3Mixin,
        GeoFlowConnectorPlugin,
    ):
        pass

    return GeoFlowConnectorPluginV073(iface)
