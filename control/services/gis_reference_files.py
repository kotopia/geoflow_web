"""Bounded original-file inspection. Never extract/execute uploaded archives."""

import hashlib
import os
import stat
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import SpooledTemporaryFile, TemporaryDirectory

from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError

from control.services.gis_references import ReferenceError

MAX_BYTES = 100 * 1024 * 1024
MAX_EXPANDED = 300 * 1024 * 1024
SUFFIXES = {".zip", ".gpkg", ".geojson", ".csv", ".xlsx", ".pdf"}
ZIP_MEMBERS = {
    ".shp",
    ".shx",
    ".dbf",
    ".prj",
    ".cpg",
    ".qix",
    ".sbn",
    ".sbx",
    ".xml",
    ".txt",
    ".gpkg",
    ".geojson",
    ".csv",
    ".xlsx",
    ".pdf",
}


class ReferenceStorageError(RuntimeError):
    pass


def uploads_enabled():
    # The private bucket is the existing application store. Explicit false still disables intake.
    return (
        bool(os.environ.get("AWS_S3_BUCKET"))
        and os.environ.get("GEOFLOW_CENTRAL_REFERENCE_UPLOAD_ENABLED", "true").lower()
        == "true"
    )


def inspect_zip(stream, xlsx=False):
    try:
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            if (
                not entries
                or len(entries) > 2000
                or sum(i.file_size for i in entries) > MAX_EXPANDED
            ):
                raise ReferenceError(
                    "압축파일의 항목 수 또는 해제 크기 제한을 초과했습니다."
                )
            names = set()
            for entry in entries:
                path = PurePosixPath(entry.filename)
                name = entry.filename.casefold()
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in name
                    or ":" in name
                    or "\x00" in name
                    or name in names
                    or entry.flag_bits & 1
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or entry.file_size > max(entry.compress_size, 1) * 200
                ):
                    raise ReferenceError("안전하지 않거나 암호화된 압축파일입니다.")
                names.add(name)
                if (
                    not xlsx
                    and not entry.is_dir()
                    and path.suffix.lower() not in ZIP_MEMBERS
                ):
                    raise ReferenceError(
                        "지원하지 않는 파일이 압축파일에 포함되어 있습니다."
                    )
                if xlsx and path.suffix.lower() not in {
                    ".xml",
                    ".rels",
                    ".png",
                    ".jpeg",
                    ".jpg",
                    "",
                }:
                    raise ReferenceError(
                        "매크로 또는 지원하지 않는 Excel 구성요소입니다."
                    )
            if xlsx and not {"[content_types].xml", "xl/workbook.xml"} <= names:
                raise ReferenceError("올바른 XLSX 파일이 아닙니다.")
            for name in names:
                if (
                    name.endswith(".shp")
                    and not {name[:-4] + s for s in (".shx", ".dbf", ".prj")} <= names
                ):
                    raise ReferenceError("SHP의 SHX·DBF·PRJ 구성 파일이 필요합니다.")
            if archive.testzip():
                raise ReferenceError("압축파일의 무결성 검사에 실패했습니다.")
    except (
        zipfile.BadZipFile,
        NotImplementedError,
        RuntimeError,
        OSError,
        EOFError,
        zlib.error,
    ):
        raise ReferenceError("압축파일을 읽을 수 없습니다.") from None


def prepare(upload):
    filename = str(upload.name)
    suffix = PurePosixPath(filename).suffix.lower()
    if (
        suffix not in SUFFIXES
        or len(filename) > 180
        or "/" in filename
        or "\\" in filename
        or any(ord(c) < 32 for c in filename)
    ):
        raise ReferenceError("ZIP·GPKG·GeoJSON·CSV·XLSX·PDF 파일을 선택하세요.")
    # Ownership passes to the caller; close on every failure below.
    stream = SpooledTemporaryFile(max_size=4 * 1024 * 1024)  # noqa: SIM115
    try:
        size = 0
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            size += len(chunk)
            if size > MAX_BYTES:
                raise ReferenceError("원본 파일은 100MB 이하여야 합니다.")
            digest.update(chunk)
            stream.write(chunk)
        if size == 0:
            raise ReferenceError("빈 파일은 등록할 수 없습니다.")
        stream.seek(0)
        if suffix in {".zip", ".xlsx"}:
            inspect_zip(stream, xlsx=suffix == ".xlsx")
        # Original intake only: CRS, geometry, field semantics are NOT verified here.
        stream.seek(0)
        return stream, {
            "filename": filename,
            "suffix": suffix,
            "size": size,
            "sha256": digest.hexdigest(),
        }
    except Exception:
        stream.close()
        raise


def store(stream, key):
    if not uploads_enabled():
        raise ReferenceError("원본 파일 저장이 아직 활성화되지 않았습니다.")
    from geoflow_ops.services.s3_service import (
        get_bucket_name,
        get_s3_client,
        get_sse_config,
    )

    try:
        get_s3_client().upload_fileobj(
            stream,
            get_bucket_name(),
            key,
            ExtraArgs={
                **get_sse_config(),
                "ContentType": "application/octet-stream",
                "ContentDisposition": "attachment",
            },
        )
    except (BotoCoreError, ClientError, S3UploadFailedError, OSError, ValueError):
        raise ReferenceStorageError("Reference original storage unavailable") from None


def download_url(key, filename):
    from geoflow_ops.services.s3_service import generate_presigned_get_url

    try:
        return generate_presigned_get_url(
            key,
            expires_in=60,
            content_type="application/octet-stream",
            disposition="attachment",
            filename=filename,
        )
    except (BotoCoreError, ClientError, OSError, ValueError):
        raise ReferenceStorageError("Reference original download unavailable") from None


@contextmanager
def local_original(version):
    """Bounded verified local copy, removed on success/error; never a project attachment."""
    from geoflow_ops.services.s3_service import get_bucket_name, get_s3_client

    with TemporaryDirectory(prefix="geoflow-reference-") as directory:
        root = Path(directory)
        suffix = Path(version["filename"]).suffix.lower()
        path = root / ("original" + suffix)
        body = None
        try:
            response = get_s3_client().get_object(
                Bucket=get_bucket_name(), Key=version["object_key"]
            )
            body = response["Body"]
            digest, total = hashlib.sha256(), 0
            with path.open("wb") as output:
                while chunk := body.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ReferenceError("원본 파일 크기 제한을 초과했습니다.")
                    digest.update(chunk)
                    output.write(chunk)
            if (
                total != version["size_bytes"]
                or digest.hexdigest() != version["sha256"]
            ):
                raise ReferenceError("원본 파일의 크기·해시가 등록 정보와 다릅니다.")
            if suffix == ".zip":
                with path.open("rb") as stream:
                    inspect_zip(stream)
                with zipfile.ZipFile(path) as archive:
                    total = 0
                    for entry in archive.infolist():
                        destination = root / "unpacked" / entry.filename
                        if not destination.resolve().is_relative_to(
                            (root / "unpacked").resolve()
                        ):
                            raise ReferenceError("안전하지 않은 압축 경로입니다.")
                        if entry.is_dir():
                            continue
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with (
                            archive.open(entry) as source,
                            destination.open("xb") as target,
                        ):
                            while chunk := source.read(1024 * 1024):
                                total += len(chunk)
                                if total > MAX_EXPANDED:
                                    raise ReferenceError(
                                        "압축 해제 크기 제한을 초과했습니다."
                                    )
                                target.write(chunk)
            yield root
        except (BotoCoreError, ClientError, OSError):
            raise ReferenceStorageError("Reference original read unavailable") from None
        finally:
            if body is not None:
                body.close()
