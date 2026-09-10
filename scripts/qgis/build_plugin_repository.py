#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import hashlib
from pathlib import Path, PurePosixPath
import re
import stat
import xml.etree.ElementTree as ET
import zipfile


PACKAGE_DIR = "geoflow_connector"
VERSION_RE = re.compile(r"\A[0-9]+\.[0-9]+\.[0-9]+\Z")
EXCLUDED_NAMES = {"__pycache__", ".DS_Store"}


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
        if path.is_dir():
            continue
        if path.suffix in {".pyc", ".pyo"} or path.name.startswith("test_"):
            continue
        yield path, PurePosixPath(PACKAGE_DIR, *relative.parts)


def build_zip(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, archive_path in package_files(source):
            info = zipfile.ZipInfo(str(archive_path), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def build_xml(values: dict[str, str], download_url: str, filename: str, digest: str) -> bytes:
    experimental = values.get("experimental", "false").strip().lower()
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
        ("file_name", filename),
        ("download_url", download_url),
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
    args = parser.parse_args()
    values = metadata(args.source)
    filename = f"{PACKAGE_DIR}-{values['version']}.zip"
    package = args.output / "releases" / filename
    digest = build_zip(args.source, package)
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
