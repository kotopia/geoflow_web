"""Run via QGIS --code in an isolated profile containing only the release ZIP."""
import importlib
import json
import os
from pathlib import Path
import pkgutil
import traceback
from qgis.PyQt.QtCore import QTimer
from qgis.core import Qgis, QgsApplication, QgsProject, QgsVectorLayer, QgsVectorFileWriter
import qgis.utils

CONFIG = json.loads(Path(os.environ['GEOFLOW_RELEASE_CHECK']).read_text(encoding='utf-8'))


def check():
    result = {'phase': CONFIG['phase'], 'runtime': Qgis.QGIS_VERSION, 'pid': os.getpid()}
    try:
        expected = Path(CONFIG['plugin_root']).resolve()
        assert not Path(qgis.utils.__file__).resolve().is_relative_to(expected)
        qgis.utils.updateAvailablePlugins()
        assert qgis.utils.pluginMetadata('geoflow_connector', 'version') == '1.4.3'
        assert qgis.utils.loadPlugin('geoflow_connector')
        assert qgis.utils.startPlugin('geoflow_connector')
        package = importlib.import_module('geoflow_connector')
        assert Path(package.__file__).resolve().parent == expected
        modules = []
        for module in pkgutil.walk_packages(package.__path__, package.__name__ + '.'):
            imported = importlib.import_module(module.name)
            if getattr(imported, '__file__', None):
                assert Path(imported.__file__).resolve().is_relative_to(expected), module.name
            modules.append(module.name)
        plugin = qgis.utils.plugins['geoflow_connector']
        plugin._ensure_ui()
        plugin._ensure_work()
        assert plugin.dialog is not None and plugin.work is not None
        result.update(version='1.4.3', plugin_root=str(expected), modules_imported=len(modules),
                      class_factory=True, init_gui=True, login_ui=True, dynamic_form_host=True)
        project = QgsProject.instance()
        if CONFIG['phase'] == 1:
            layer = QgsVectorLayer('Point?crs=EPSG:4326&field=id:string', 'release-reload-check', 'memory')
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = 'GPKG'
            gpkg = str(Path(CONFIG['profile_root']) / 'reload.gpkg')
            outcome = QgsVectorFileWriter.writeAsVectorFormatV3(layer, gpkg, project.transformContext(), options)
            assert outcome[0] == QgsVectorFileWriter.NoError, outcome
            persistent = QgsVectorLayer(gpkg, 'release-reload-check', 'ogr')
            assert persistent.isValid()
            project.addMapLayer(persistent)
            assert project.write(CONFIG['project'])
        else:
            assert project.read(CONFIG['project'])
            assert any(layer.name() == 'release-reload-check' and layer.isValid()
                       for layer in project.mapLayers().values())
        result['project_save_or_reload'] = True
        assert qgis.utils.unloadPlugin('geoflow_connector')
        result['ok'] = True
    except Exception:
        result.update(ok=False, error=traceback.format_exc())
    Path(CONFIG['result']).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    QgsProject.instance().clear()
    QgsApplication.exit(0 if result['ok'] else 1)


QTimer.singleShot(1000, check)
