"""Build a deterministic, allowlisted QGIS ZIP; never publish or access credentials."""
import ast
import configparser
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'release'
PACKAGE = 'geoflow_connector'
RUNTIME_DIRS = {'api', 'app', 'cache', 'forms', 'layers', 'resources', 'services', 'survey', 'sync', 'ui'}
ROOT_FILES = {'__init__.py', 'metadata.txt', 'photo_selection.py', 'realtime_auth.py', 'CHANGELOG.md'}
EXCLUDED = {'__pycache__', '.git', '.github', '.vscode', '.pytest_cache', 'node_modules'}
SUFFIXES = {'.py', '.ui', '.qss', '.qml', '.svg', '.png', '.jpg', '.jpeg', '.ico', '.qrc', '.json', '.txt', '.md', '.db'}


def included(path):
    rel = path.relative_to(ROOT)
    if path.is_symlink() or any(part in EXCLUDED or part.startswith('.') for part in rel.parts):
        return False
    if len(rel.parts) == 1:
        return path.name in ROOT_FILES
    return rel.parts[0] in RUNTIME_DIRS and (path.suffix.lower() in SUFFIXES or path.name in {'LICENSE', 'NOTICE'})


def build(repository_builder):
    global OUT
    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT / 'metadata.txt', encoding='utf-8')
    meta = config['general']
    version = meta['version']
    previous_version = json.loads((ROOT / 'release' / 'geoflow_connector-release.json').read_text(encoding='utf-8'))['version']
    assert tuple(map(int, version.split('.'))) > tuple(map(int, previous_version.split('.')))
    OUT = ROOT / 'release' / version
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / f'{PACKAGE}-{version}.zip').exists():
        raise FileExistsError('Refusing to overwrite a release ZIP')
    reference = ET.parse(ROOT / 'release' / 'test-repository-reference.xml').getroot()
    previous = reference.find('pyqgis_plugin')
    assert tuple(map(int, version.split('.'))) > tuple(map(int, previous.attrib['version'].split('.')))
    assert meta['name'] == previous.attrib['name']
    assert not meta.getboolean('experimental') and not meta.getboolean('deprecated')
    paths = sorted(p for p in ROOT.rglob('*') if p.is_file() and included(p))
    findings = []
    retired = re.compile(r'survey-links|survey_link|SurveyTargetLink|no_linked_survey|survey_links_exist', re.I)
    secret_patterns = {
        'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'aws_access_key': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
        'github_token': r'\b(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}',
        'jwt_literal': r'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}',
        'user_path': r'[A-Za-z]:[\\/]Users[\\/][^\s"\']+',
    }
    inventory = []
    for path in paths:
        data = path.read_bytes()
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix in {'.py', '.ui', '.json', '.txt', '.qss', '.qml', '.qrc', '.md'}:
            content = data.decode('utf-8-sig')
            for label, pattern in secret_patterns.items():
                if re.search(pattern, content):
                    findings.append({'file': rel, 'kind': label})
            if path.suffix == '.py':
                ast.parse(content, filename=rel)
                if retired.search(content):
                    findings.append({'file': rel, 'kind': 'retired_runtime_reference'})
                # Report only the name/location of suspicious credential assignments, never values.
                for node in ast.walk(ast.parse(content)):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        for target in targets:
                            name = target.id if isinstance(target, ast.Name) else ''
                            if (re.fullmatch(r'(?:password|api_key|secret|access_token|auth_token)', name, re.I)
                                    and isinstance(node.value.value, str) and len(node.value.value) > 8):
                                findings.append({'file': rel, 'kind': 'credential_assignment', 'line': node.lineno})
        inventory.append({'path': rel, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    (OUT / 'package-audit.json').write_text(json.dumps({
        'files': len(paths), 'findings': findings,
        'excluded_categories': ['tests', 'test_artifacts', 'docs', 'scripts', 'release', 'bytecode', 'local settings/logs'],
        'cache_note': 'cache/*.py is required runtime code, not user cache data.',
        'method': 'allowlist + AST parsing + known credential/private-key/token/user-path patterns; authentication parameter names are not secrets',
    }, indent=2), encoding='utf-8')
    assert not findings, 'Package audit needs review; see package-audit.json (no secret values printed)'
    filename = f'{PACKAGE}-{version}.zip'
    target = OUT / filename
    spec = importlib.util.spec_from_file_location('repository_builder', repository_builder)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    # Assert identical exclusions, then reuse the repository's archive/XML implementation.
    assert {p for p, _ in builder.package_files(ROOT)} == set(paths)
    builder.build_zip(ROOT, target)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert all(n.startswith(PACKAGE + '/') for n in archive.namelist())
        assert f'{PACKAGE}/metadata.txt' in archive.namelist()
        assert f'{PACKAGE}/__init__.py' in archive.namelist()
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    missing = [key for key in ('email', 'repository', 'tracker') if not meta.get(key, '').strip()]
    manifest = {
        'plugin_name': meta['name'], 'package_name': PACKAGE, 'version': version,
        'previous_version': previous_version, 'zip_filename': filename,
        'size_bytes': target.stat().st_size, 'sha256': digest,
        'qgis_minimum_version': meta['qgisMinimumVersion'], 'qgis_maximum_version': meta['qgisMaximumVersion'],
        'experimental': False, 'deprecated': False, 'zip_root': PACKAGE + '/',
        'download_url': f'https://geoflow.co.kr/gis/qgis/plugins/releases/{filename}',
        'download_url_status': 'proposed_only_not_published',
        'metadata': dict(meta), 'missing_publisher_metadata': missing,
        'publication_ready': False, 'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'publication_note': 'Work must review metadata, validation reports and destination before publishing.',
    }
    (OUT / 'geoflow_connector-release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / (filename + '.sha256')).write_text(f'{digest}  {filename}\n', encoding='ascii')
    (OUT / 'package-files.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    xml = builder.build_xml(dict(meta), manifest['download_url'], filename, digest)
    assert [c.tag for c in ET.fromstring(xml).find('pyqgis_plugin')] == [c.tag for c in previous]
    assert ET.fromstring(xml).findtext('pyqgis_plugin/file_name') == 'geoflow_connector.zip'
    (OUT / 'plugin-entry.xml').write_bytes(xml)
    print(json.dumps({'filename':filename, 'files':len(paths), 'size':target.stat().st_size, 'sha256':digest, 'missing_metadata':missing}))


if __name__ == '__main__':
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parents[2] / 'scripts/qgis/build_plugin_repository.py')
