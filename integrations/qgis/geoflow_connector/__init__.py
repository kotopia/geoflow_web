def classFactory(iface):
    from .app.unified import UnifiedMixin
    from .app.integration import ConnectorIntegrationMixin
    from .cache.qgis_lifecycle import CacheLifecycleMixin
    from .sync.delta_apply import DeltaApplyMixin
    from .ui.layer_workspace import LayerWorkspaceMixin
    from .app.plugin import GeoFlowConnectorPlugin
    from .sync.realtime import RealtimeMixin
    from .sync.session_guard import RealtimeSessionGuardMixin
    from .cache.reuse import SnapshotReuseMixin

    class GeoFlowConnectorPluginV121(
        UnifiedMixin,
        ConnectorIntegrationMixin,
        CacheLifecycleMixin,
        RealtimeSessionGuardMixin,
        RealtimeMixin,
        LayerWorkspaceMixin,
        SnapshotReuseMixin,
        DeltaApplyMixin,
        GeoFlowConnectorPlugin,
    ):
        pass

    return GeoFlowConnectorPluginV121(iface)
