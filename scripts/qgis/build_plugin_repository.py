#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import xml.etree.ElementTree as ET
import zipfile


PACKAGE_DIR = "geoflow_connector"
QGIS_REPOSITORY_FILE_NAME = f"{PACKAGE_DIR}.zip"
VERSION_RE = re.compile(r"\A[0-9]+\.[0-9]+\.[0-9]+\Z")
EXCLUDED_NAMES = {"__pycache__", ".DS_Store", ".git", ".github", ".vscode", ".pytest_cache",
                  "tests", "test_artifacts", "release", "scripts", "docs", "logs"}
RUNTIME_DIRECTORIES = {"api", "app", "cache", "forms", "layers", "resources", "services", "survey", "sync", "ui"}
ROOT_FILES = {"__init__.py", "metadata.txt", "photo_selection.py", "realtime_auth.py", "CHANGELOG.md"}
RUNTIME_SUFFIXES = {".py", ".ui", ".qss", ".qml", ".svg", ".png", ".jpg", ".jpeg", ".ico", ".qrc", ".json", ".txt", ".md", ".db"}


def metadata(source: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(source / "metadata.txt", encoding="utf-8")
    if not parser.has_section("general"):
        raise ValueError("metadata.txt is missing [general]")
    values = dict(parser.items("general"))
    version = values.get("version", "")
    if not VERSION_RE.fullmatch(version):
        raise ValueError("QGIS plugin version must be semantic x.y.z")
    if values.get("name") != "GeoFlow Connector":
        raise ValueError("Unexpected QGIS plugin name")
    return values


def package_files(source: Path):
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.is_dir() or path.is_symlink():
            continue
        if any(part.startswith('.') for part in relative.parts):
            continue
        if len(relative.parts) == 1 and path.name not in ROOT_FILES:
            continue
        if len(relative.parts) > 1 and relative.parts[0] not in RUNTIME_DIRECTORIES:
            continue
        if path.suffix.lower() not in RUNTIME_SUFFIXES and path.name not in {'LICENSE', 'NOTICE'}:
            continue
        yield path, PurePosixPath(PACKAGE_DIR, *relative.parts)


def release_payloads(source: Path, manifest: Path, inventory: Path):
    release = json.loads(manifest.read_text(encoding='utf-8'))
    values = metadata(source)
    if release['version'] != values['version'] or release['zip_filename'] != f"{PACKAGE_DIR}-{values['version']}.zip":
        raise ValueError('Release version/filename mismatch')
    if release.get('experimental') is not False or release.get('deprecated') is not False:
        raise ValueError('Stable release flags must be false')
    if values.get('experimental','').lower() != 'false' or values.get('deprecated','').lower() != 'false':
        raise ValueError('Stable metadata flags must be false')
    expected = json.loads(inventory.read_text(encoding='utf-8'))
    actual = {str(name.relative_to(PACKAGE_DIR)): path for path,name in package_files(source)}
    if len(expected) != len(actual) or {item['path'] for item in expected} != set(actual):
        raise ValueError('Release file inventory differs from runtime allowlist')
    result = []
    for item in expected:
        path = actual[item['path']]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            # Git text normalization must not change the approved Windows ZIP.
            # Reconstruct only when the declared per-file hash proves the bytes.
            data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('Release file bytes differ: ' + item['path'])
        result.append((data, PurePosixPath(PACKAGE_DIR,item['path'])))
    result.sort(key=lambda item: PureWindowsPath(str(item[1])))
    return release, result


def build_zip(source: Path, destination: Path, *, release_manifest: Path | None = None,
              inventory: Path | None = None) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    release = None
    if release_manifest is not None:
        if inventory is None:
            raise ValueError('Release inventory is required')
        release, files = release_payloads(source, release_manifest, inventory)
    else:
        files = [(path.read_bytes(), name) for path,name in package_files(source)]
    directories = {PurePosixPath(PACKAGE_DIR)}
    for _, archive_path in files:
        directories.update(
            parent
            for parent in archive_path.parents
            if parent != PurePosixPath(".")
        )
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for archive_path in sorted(directories):
            info = zipfile.ZipInfo(
                str(archive_path).rstrip("/") + "/",
                date_time=(2026, 1, 1, 0, 0, 0),
            )
            if release is not None:
                info.create_system = 0
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
            archive.writestr(info, b"")
        for data, archive_path in files:
            info = zipfile.ZipInfo(str(archive_path), date_time=(2026, 1, 1, 0, 0, 0))
            if release is not None:
                info.create_system = 0
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    if release is not None and (digest != release['sha256'] or destination.stat().st_size != release['size_bytes']):
        destination.unlink()
        raise ValueError('Approved ZIP SHA256/size mismatch; publication prohibited')
    return digest


def build_xml(values: dict[str, str], download_url: str, filename: str, digest: str) -> bytes:
    experimental = values.get("experimental", "false").strip().lower()
    if download_url.rsplit("/", 1)[-1] != filename:
        raise ValueError("QGIS package filename does not match download URL")
    root = ET.Element("plugins")
    plugin = ET.SubElement(
        root,
        "pyqgis_plugin",
        name=values["name"],
        version=values["version"],
        experimental=experimental,
    )
    fields = (
        ("name", values["name"]),
        ("version", values["version"]),
        ("qgis_minimum_version", values.get("qgisminimumversion", "")),
        ("qgis_maximum_version", values.get("qgismaximumversion", "")),
        ("description", values.get("description", "")),
        ("about", values.get("about", "")),
        ("author_name", values.get("author", "GeoFlow")),
        ("homepage", values.get("homepage", "https://geoflow.co.kr")),
        ("repository", values.get("repository", "")),
        ("tracker", values.get("tracker", "")),
        ("tags", values.get("tags", "")),
        ("downloads", "0"),
        # QGIS derives the plugin id from everything before the first dot in
        # file_name.  Keep this logical name stable while download_url points
        # at the immutable, versioned S3 object.
        ("file_name", QGIS_REPOSITORY_FILE_NAME),
        ("download_url", download_url),
        ("experimental", experimental),
        ("deprecated", values.get("deprecated", "false").strip().lower()),
        ("trusted", "false"),
        ("sha256_sum", digest),
    )
    for name, value in fields:
        ET.SubElement(plugin, name).text = value
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-url", default="https://geoflow.co.kr/gis/qgis/plugins/releases"
    )
    parser.add_argument("--release-manifest", type=Path)
    parser.add_argument("--inventory", type=Path)
    args = parser.parse_args()
    values = metadata(args.source)
    filename = f"{PACKAGE_DIR}-{values['version']}.zip"
    package = args.output / "releases" / filename
    digest = build_zip(args.source, package, release_manifest=args.release_manifest, inventory=args.inventory)
    repository = args.output / "plugins.xml"
    repository.parent.mkdir(parents=True, exist_ok=True)
    repository.write_bytes(
        build_xml(
            values,
            f"{args.base_url.rstrip('/')}/{filename}",
            filename,
            digest,
        )
    )
    print(f"package={package}")
    print(f"repository={repository}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
