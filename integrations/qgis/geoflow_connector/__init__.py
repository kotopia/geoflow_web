def classFactory(iface):
    from .plugin import GeoFlowConnectorPlugin

    return GeoFlowConnectorPlugin(iface)
