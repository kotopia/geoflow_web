def classFactory(iface):
    from .delta_apply_v3 import DeltaApplyV3Mixin
    from .plugin import GeoFlowConnectorPlugin
    from .realtime_delta_v3 import RealtimeDeltaV3Mixin
    from .snapshot_reuse import SnapshotReuseMixin

    class GeoFlowConnectorPluginV070(
        RealtimeDeltaV3Mixin,
        SnapshotReuseMixin,
        DeltaApplyV3Mixin,
        GeoFlowConnectorPlugin,
    ):
        pass

    return GeoFlowConnectorPluginV070(iface)
