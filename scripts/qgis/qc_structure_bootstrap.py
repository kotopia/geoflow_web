"""CI-only QGIS application entry point for the isolated two-launch test."""
import os
from pathlib import Path
import runpy
import traceback

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QSettings, QTimer
from qgis import utils


def smoke():
    result = Path(os.environ["GEOFLOW_QGIS_QC_RESULT"])
    phase = os.environ["GEOFLOW_QGIS_QC_PHASE"]
    packages = ("geoflow_connector", "geoflow_qc_structure")
    try:
        assert Path(QgsApplication.qgisSettingsDirPath()).name == "qc_structure_test"
        if phase == "initial":
            utils.updateAvailablePlugins()
            for package in packages:
                if package not in utils.plugins:
                    assert utils.loadPlugin(package), package
                    assert utils.startPlugin(package), package
        assert all(package in utils.plugins for package in packages), utils.active_plugins
        runpy.run_path(os.environ["GEOFLOW_QGIS_QC_FIXTURE"])
        settings = QSettings()
        if phase == "initial":
            for package in reversed(packages):
                assert utils.unloadPlugin(package), package
            for package in packages:
                assert utils.loadPlugin(package), package
                assert utils.startPlugin(package), package
                settings.setValue(f"PythonPlugins/{package}", True)
            settings.sync()
        result.write_text(f"PASS {phase}", encoding="utf-8")
    except Exception:
        result.write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        QgsApplication.quit()


QTimer.singleShot(1500, smoke)
