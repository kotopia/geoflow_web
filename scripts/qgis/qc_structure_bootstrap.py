"""CI-only QGIS application entry point for the isolated two-launch test."""
import faulthandler
import os
from pathlib import Path
import runpy
import traceback

faulthandler.enable()
print("QC smoke: Python startup script reached", flush=True)

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import QSettings, QTimer
from qgis import utils


def smoke():
    result = Path(os.environ["GEOFLOW_QGIS_QC_RESULT"])
    phase = os.environ["GEOFLOW_QGIS_QC_PHASE"]
    packages = ("geoflow_connector", "geoflow_qc_structure")
    try:
        assert Path(QgsApplication.qgisSettingsDirPath()).name == "qc_structure_test"
        print(f"QC smoke: profile confirmed; phase={phase}", flush=True)
        if phase == "initial":
            utils.updateAvailablePlugins()
            for package in packages:
                if package not in utils.plugins:
                    print(f"QC smoke: loading {package}", flush=True)
                    assert utils.loadPlugin(package), package
                    assert utils.startPlugin(package), package
        assert all(package in utils.plugins for package in packages), utils.active_plugins
        print("QC smoke: both plugins enabled; checking fixtures", flush=True)
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
        # The disposable fixture changes the project dirty flag even after layer cleanup.
        QgsProject.instance().setDirty(False)
        QgsApplication.quit()


QTimer.singleShot(1500, smoke)
