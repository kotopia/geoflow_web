"""Real QGIS process checks; only the isolated profile receives writes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(os.environ['GEOFLOW_COMMON_FORM_ROOT'])
sys.path.insert(0, str(ROOT.parent))
from qgis.PyQt.QtCore import QSettings, QTimer
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsApplication
from unittest.mock import patch
from geoflow_connector.forms.dynamic.layout_editor import LocalFormLayoutStore, FormLayoutEditor
from geoflow_connector.forms.dynamic.layout_model import (
    BUNDLED_COMMON_FORM, bundled_default_layout, default_layout, normalize_layout,
    placed_field_ids,
)
from geoflow_connector.forms.dynamic.form import DynamicForm


def fields_for(layout):
    return [dict(id=fid, label=fid, widget_type='text', visible=True,
                 readonly=False, required=False, codes=[])
            for fid in placed_field_ids(layout)]


def check():
    phase = int(os.environ['GEOFLOW_COMMON_FORM_PHASE'])
    result = {'phase': phase, 'pid': os.getpid(), 'ok': False}
    try:
        before = BUNDLED_COMMON_FORM.read_bytes()
        layouts = json.loads(before)['layouts']
        settings = QSettings()
        # Never point this test's writes at the real developer profile.
        assert 'geoflow-common-form-check' in settings.fileName()
        store = LocalFormLayoutStore(settings)
        layer = 'WTL_PIPE_PS'
        fields = fields_for(layouts[layer])
        if phase == 1:
            original = QSettings(str(ROOT.parents[2] / 'QGIS/QGIS4.ini'), QSettings.Format.IniFormat)
            for standard, saved in layouts.items():
                raw = original.value(store.key(standard), '', type=str)
                assert json.loads(raw) == saved
                layer_fields = fields_for(saved)
                expected = normalize_layout(saved, standard, layer_fields)
                assert LocalFormLayoutStore(original).load(standard, layer_fields) == expected
                assert store.load(standard, layer_fields) == expected
                assert not settings.contains(store.key(standard))
                form = DynamicForm({}, layer_fields, layer=standard, form_layout=store.load(standard, layer_fields))
                assert form.form_layout == expected
                assert original.value(store.key(standard), '', type=str) == raw
                form.close()
            result['local_original_and_new_profile_match_layers'] = len(layouts)
            other = fields_for(layouts[layer])
            assert store.load('UNBUNDLED_LAYER', other) == default_layout('UNBUNDLED_LAYER', other)
            # Corrupt overrides are preserved on disk while rendering the fallback.
            settings.setValue(store.key(layer), '{invalid')
            assert store.load(layer, fields) == bundled_default_layout(layer, fields)
            assert settings.value(store.key(layer)) == '{invalid'
            store.reset(layer)
            custom = copy.deepcopy(store.load(layer, fields))
            custom['tabs'][0]['groups'][0]['title'] = 'User override persistence check'
            store.save(layer, fields, custom)
            assert store.load(layer, fields) == custom
            editor = FormLayoutEditor(layer, fields, custom)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                editor._request_reset()
            assert editor.reset_requested
            assert editor.value() == bundled_default_layout(layer, fields)
            # Previewing reset does not modify the saved override until accepted.
            assert store.load(layer, fields) == custom
            editor.close()
            result['save_override_and_reset_preview'] = True
        else:
            assert settings.contains(store.key(layer))
            assert store.load(layer, fields)['tabs'][0]['groups'][0]['title'] == 'User override persistence check'
            store.reset(layer)
            assert not settings.contains(store.key(layer))
            assert store.load(layer, fields) == bundled_default_layout(layer, fields)
            result['restart_override_and_remove_fallback'] = True
        assert BUNDLED_COMMON_FORM.read_bytes() == before
        result.update(ok=True, resource_sha256=hashlib.sha256(before).hexdigest(), resource_unchanged=True)
    except Exception:
        result['error'] = traceback.format_exc()
    Path(os.environ['GEOFLOW_COMMON_FORM_RESULT']).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    QgsApplication.exit(0 if result['ok'] else 1)


QTimer.singleShot(1000, check)
