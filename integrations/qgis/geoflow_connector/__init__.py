def classFactory(iface):
    from .delta_apply_v3 import DeltaApplyV3Mixin
    from .plugin import GeoFlowConnectorPlugin
    from .realtime_delta import RealtimeDeltaMixin

    class GeoFlowConnectorPluginV060(
        RealtimeDeltaMixin,
        DeltaApplyV3Mixin,
        GeoFlowConnectorPlugin,
    ):
        pass

    return GeoFlowConnectorPluginV060(iface)
