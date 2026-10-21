"""QGIS runtime proof that local queue management is disabled."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from qgis.core import QgsApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.app.unified import UnifiedMixin


APP = QgsApplication.instance() or QgsApplication([], False)
APP.initQgis()

bar = SimpleNamespace(pushMessage=Mock())
engine = SimpleNamespace(iface=SimpleNamespace(messageBar=lambda: bar))
UnifiedMixin.show_sync_center(engine)
bar.pushMessage.assert_called_once()
message = bar.pushMessage.call_args.args[1]
assert "로컬 동기화 큐를 사용하지 않습니다" in message
assert not (Path(__file__).resolve().parents[1] / "sync" / "queue.py").exists()
assert not (Path(__file__).resolve().parents[1] / "sync" / "photo_queue.py").exists()
assert not (Path(__file__).resolve().parents[1] / "ui" / "sync_center.py").exists()

print("qgis online-only sync center runtime: OK")
