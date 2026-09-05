def classFactory(iface):
    from .delta_apply_v3 import DeltaApplyV3Mixin
    from .plugin import GeoFlowConnectorPlugin
    from .realtime_delta_v2 import RealtimeDeltaV2Mixin

    class GeoFlowConnectorPluginV062(
        RealtimeDeltaV2Mixin,
        DeltaApplyV3Mixin,
        GeoFlowConnectorPlugin,
    ):
        pass

    return GeoFlowConnectorPluginV062(iface)
