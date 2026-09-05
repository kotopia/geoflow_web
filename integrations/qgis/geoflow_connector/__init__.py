def classFactory(iface):
    from .delta_apply_v2 import DeltaApplyV2Mixin
    from .plugin import GeoFlowConnectorPlugin

    class GeoFlowConnectorPluginV051(DeltaApplyV2Mixin, GeoFlowConnectorPlugin):
        pass

    return GeoFlowConnectorPluginV051(iface)
