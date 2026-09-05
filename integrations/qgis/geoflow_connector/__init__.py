def classFactory(iface):
    from .delta_apply_v3 import DeltaApplyV3Mixin
    from .plugin import GeoFlowConnectorPlugin

    class GeoFlowConnectorPluginV052(DeltaApplyV3Mixin, GeoFlowConnectorPlugin):
        pass

    return GeoFlowConnectorPluginV052(iface)
