def classFactory(iface):
    from .cache_lifecycle_qgis import CacheLifecycleMixin
    from .delta_apply_v3 import DeltaApplyV3Mixin
    from .layer_workspace import LayerWorkspaceMixin
    from .plugin import GeoFlowConnectorPlugin
    from .realtime_delta_v3 import RealtimeDeltaV3Mixin
    from .realtime_session_guard import RealtimeSessionGuardMixin
    from .snapshot_reuse import SnapshotReuseMixin

    class GeoFlowConnectorPluginV080(
        CacheLifecycleMixin,
        RealtimeSessionGuardMixin,
        RealtimeDeltaV3Mixin,
        LayerWorkspaceMixin,
        SnapshotReuseMixin,
        DeltaApplyV3Mixin,
        GeoFlowConnectorPlugin,
    ):
        pass

    return GeoFlowConnectorPluginV080(iface)
