"""QGIS 4 runtime checks for QGIS-buffer exit policy."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from qgis.core import QgsApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.app.unified import UnifiedMixin


APP = QgsApplication.instance() or QgsApplication([], False)
APP.initQgis()


def engine(*, work_allows=True, sync_error=False):
    return SimpleNamespace(
        _opening=False, _sync_in_progress=False, _last_sync_error=sync_error,
        work=SimpleNamespace(guard_transition=Mock(return_value=work_allows)),
        iface=SimpleNamespace(mainWindow=Mock(return_value=None), messageBar=Mock()),
        log=Mock(), log_exception=Mock(), _checkpoint_safely=Mock(),
    )


# Legacy queue rows are inert migration data and do not control transitions.
saved = engine(sync_error=True)
with patch("geoflow_connector.app.unified.protection.inspect", return_value={
    "drafts": [], "buffers": [],
    "queue": {"pending": 1, "outbox": 0, "conflict": 1, "photo": 2},
}), patch("geoflow_connector.app.unified.QMessageBox.question") as question:
    assert UnifiedMixin.guard_transition(saved, "QGIS 종료") is True
    question.assert_not_called()
    saved.log.assert_not_called()


# The Dynamic Form guard still blocks an actual unsaved draft.
draft = engine(work_allows=False)
with patch("geoflow_connector.app.unified.protection.inspect") as inspect:
    assert UnifiedMixin.guard_transition(draft, "QGIS 종료") is False
    inspect.assert_not_called()

print("qgis exit queue runtime: OK")
