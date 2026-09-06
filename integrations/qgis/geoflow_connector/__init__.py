def classFactory(iface):
    from .delta_apply_v3 import DeltaApplyV3Mixin
    from .plugin import GeoFlowConnectorPlugin
    from .realtime_delta_v3 import RealtimeDeltaV3Mixin

    class GeoFlowConnectorPluginV063(
        RealtimeDeltaV3Mixin,
        DeltaApplyV3Mixin,
        GeoFlowConnectorPlugin,
    ):
        pass

    return GeoFlowConnectorPluginV063(iface)
