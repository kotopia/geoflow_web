#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import os
import re
import xml.etree.ElementTree as ET

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

import django

django.setup()

from botocore.exceptions import ClientError

from geoflow_ops.services.s3_service import get_s3_client, get_sse_config


QGIS_PLUGIN_BUCKET = "geoflow-upload"
QGIS_PLUGIN_PREFIX = "qgis-plugins"
QGIS_PLUGIN_PACKAGE_RE = re.compile(
    r"\Ageoflow_connector-[0-9]+\.[0-9]+\.[0-9]+\.zip\Z"
)


def repository_object_key(channel: str) -> str:
    if channel not in {"test", "stable"}:
        fail("unsupported_channel")
    return f"{QGIS_PLUGIN_PREFIX}/{channel}/plugins.xml"


def package_object_key(filename: str) -> str:
    if not QGIS_PLUGIN_PACKAGE_RE.fullmatch(filename):
        fail("repository_package_name_invalid")
    return f"{QGIS_PLUGIN_PREFIX}/releases/{filename}"


def fail(reason: str) -> None:
    raise SystemExit(f"qgis_plugin_repository_blocker={reason}")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_package(repository: Path) -> tuple[str, str]:
    try:
        plugin = ET.fromstring(repository.read_bytes()).find("pyqgis_plugin")
    except (OSError, ET.ParseError):
        fail("repository_xml_invalid")
    if plugin is None or plugin.attrib.get("name") != "GeoFlow Connector":
        fail("repository_plugin_invalid")
    filename = str(plugin.findtext("file_name") or "").strip()
    expected_hash = str(plugin.findtext("sha256_sum") or "").strip().lower()
    package_object_key(filename)
    if len(expected_hash) != 64:
        fail("repository_sha256_invalid")
    return filename, expected_hash


def existing_head(client, key: str):
    try:
        return client.head_object(Bucket=QGIS_PLUGIN_BUCKET, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        fail(f"head_denied_{code or 'unknown'}")


def publish(channel: str, repository: Path, package: Path, confirmation: str) -> None:
    expected_confirmation = (
        f"PUBLISH_QGIS_PLUGIN:{channel}:{QGIS_PLUGIN_BUCKET}:qgis-plugins"
    )
    if confirmation != expected_confirmation:
        fail("confirmation_mismatch")
    if channel != "test":
        fail("only_test_channel_is_authorized")
    filename, expected_hash = repository_package(repository)
    if package.name != filename:
        fail("package_filename_mismatch")
    actual_hash = digest(package)
    if actual_hash != expected_hash:
        fail("package_sha256_mismatch")

    package_key = package_object_key(filename)
    repository_key = repository_object_key(channel)
    if package_key.startswith("tenants/") or repository_key.startswith("tenants/"):
        fail("tenant_prefix_forbidden")

    client = get_s3_client()
    try:
        client.put_object(
            Bucket=QGIS_PLUGIN_BUCKET,
            Key=package_key,
            Body=package.read_bytes(),
            ContentType="application/zip",
            CacheControl="public,max-age=31536000,immutable",
            Metadata={"sha256": actual_hash},
            IfNoneMatch="*",
            **get_sse_config(),
        )
        print("qgis_plugin_package=uploaded")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "")
        if code not in {"PreconditionFailed", "412", "ConditionalRequestConflict"}:
            fail(f"package_put_denied_{code or 'unknown'}")
        print("qgis_plugin_package=already_present")

    verified = existing_head(client, package_key)
    if verified is None:
        fail("package_verification_missing")
    if str(verified.get("Metadata", {}).get("sha256") or "").lower() != actual_hash:
        fail("immutable_package_collision")
    if int(verified.get("ContentLength") or -1) != package.stat().st_size:
        fail("immutable_package_collision")

    client.put_object(
        Bucket=QGIS_PLUGIN_BUCKET,
        Key=repository_key,
        Body=repository.read_bytes(),
        ContentType="application/xml; charset=utf-8",
        CacheControl="no-cache,no-store,must-revalidate",
        Metadata={"package-sha256": actual_hash},
        **get_sse_config(),
    )
    repository_head = existing_head(client, repository_key)
    if repository_head is None:
        fail("repository_verification_missing")
    if (
        str(repository_head.get("Metadata", {}).get("package-sha256") or "").lower()
        != actual_hash
    ):
        fail("repository_verification_hash_mismatch")

    print(f"qgis_plugin_bucket={QGIS_PLUGIN_BUCKET}")
    print(f"qgis_plugin_channel={channel}")
    print(f"qgis_plugin_package_key={package_key}")
    print(f"qgis_plugin_repository_key={repository_key}")
    print(f"qgis_plugin_sha256={actual_hash}")
    print("RESULT qgis_plugin_test_repository=SUCCESS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=("test", "stable"), required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    publish(args.channel, args.repository, args.package, args.confirm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
