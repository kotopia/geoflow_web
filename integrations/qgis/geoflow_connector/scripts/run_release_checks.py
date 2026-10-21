"""Run safe, local QGIS regression programs; never run live production probes."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = [
    'qgis_project_materialize_runtime.py', 'qgis_native_layer_tree_runtime.py',
    'qgis_layer_workspace_state_runtime.py', 'qgis_form_lifecycle_smoke.py',
    'qgis_online_commit_runtime.py', 'qgis_delete_action_runtime.py',
    'qgis_survey_popup_runtime.py', 'qgis_survey_creation_runtime.py',
    'qgis_survey_spatial_runtime.py', 'qgis_selection_feedback_runtime.py',
    'qgis_settings_nearby_runtime.py', 'qgis_field_tools_runtime.py',
    'qgis_edit_tools_integration_runtime.py', 'qgis_photo_local_runtime.py',
    'qgis_form_header_photo_runtime.py', 'qgis_default_style_runtime.py',
]


def run(name):
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8',
               PYTHONPATH=str(ROOT.parent) + os.pathsep + os.environ.get('PYTHONPATH', ''))
    command = [sys.executable, str(ROOT / 'tests' / name)]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=180)
    output = result.stdout.decode('utf-8', errors='replace') + result.stderr.decode('utf-8', errors='replace')
    log = ROOT / 'release' / 'validation' / (name + '.txt')
    log.parent.mkdir(exist_ok=True)
    log.write_text(output, encoding='utf-8')
    return {'test':name, 'exit_code':result.returncode, 'log':log.relative_to(ROOT).as_posix()}


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run, PROGRAMS))
    (ROOT / 'release' / 'regression-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results))
    raise SystemExit(int(any(row['exit_code'] for row in results)))
