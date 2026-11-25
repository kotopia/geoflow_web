"""Temporary reference inspection and common exact-intersection selection rules."""

import csv
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.contrib.gis.gdal import DataSource, GDALException
from django.contrib.gis.geos import GEOSException, GEOSGeometry, Point

from control.services import gis_reference_files as files
from control.services import gis_reference_vworld as vworld
from control.services import gis_references as refs

MAX_CANDIDATES = 2000


def options(cur):
    cur.execute(
        "SELECT d.id,d.name,d.kind,s.kind AS source_kind,s.url FROM gis.reference_dataset d "
        "LEFT JOIN gis.reference_source s ON s.id=d.source_id WHERE d.enabled=true "
        "AND (d.source_id IS NULL OR s.enabled=true) ORDER BY d.name,d.id"
    )
    datasets = refs.rows(cur)
    cur.execute(
        "SELECT v.id,v.dataset_id,v.label,v.declared_crs FROM gis.reference_version v "
        "JOIN gis.reference_dataset d ON d.id=v.dataset_id WHERE v.status='stored' AND d.enabled=true "
        "ORDER BY v.created_at DESC,v.id"
    )
    versions = refs.rows(cur)
    result = []
    for row in datasets:
        available = [v for v in versions if v["dataset_id"] == row["id"]]
        services = [
            {"id": key, "label": value["label"]}
            for key, value in vworld.SERVICES.items()
            if row["source_kind"] == "api"
            and row["url"] == vworld.ENDPOINT
            and value["kind"] == row["kind"]
        ]
        if available or services:
            result.append(
                {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "kind": row["kind"],
                    "services": services,
                    "versions": [
                        {
                            "id": str(v["id"]),
                            "label": v["label"],
                            "declared_crs": v["declared_crs"],
                        }
                        for v in available
                    ],
                }
            )
    return result


def geometry(value, crs="EPSG:4326"):
    try:
        if not isinstance(crs, str) or not crs.startswith("EPSG:"):
            raise ValueError
        srid = int(crs[5:])
        if not 1 <= srid <= 999999 or not isinstance(value, dict):
            raise ValueError
        result = GEOSGeometry(json.dumps(value))
        # GeoJSON defaults to 4326 in GEOS; the explicitly supplied CRS owns these coordinates.
        result.srid = srid
        if (
            result.empty
            or not result.valid
            or result.num_coords > 5000
            or result.geom_type == "GeometryCollection"
        ):
            raise ValueError
        result.transform(4326)
        bounds = result.extent
        if not all(math.isfinite(v) for v in bounds) or not (
            -180 <= bounds[0] <= bounds[2] <= 180
            and -90 <= bounds[1] <= bounds[3] <= 90
        ):
            raise ValueError
        if bounds[2] - bounds[0] > 0.02 or bounds[3] - bounds[1] > 0.02:
            raise refs.ReferenceError(
                "조회 범위가 큽니다. 객체 또는 약 2km 이내 작업 영역으로 나누세요."
            )
        return result
    except (ValueError, TypeError, GEOSException, GDALException, OverflowError):
        raise refs.ReferenceError("유효한 도형과 EPSG 좌표계를 지정하세요.") from None


def scalar_properties(value):
    if not isinstance(value, dict) or len(value) > 200:
        raise refs.ReferenceError("참조 속성 형식을 확인하세요.")
    result = {}
    for key, item in value.items():
        if isinstance(item, (date, datetime)):
            item = item.isoformat()
        elif isinstance(item, (Decimal, UUID)):
            item = str(item)
        if (
            isinstance(key, str)
            and len(key) <= 150
            and (item is None or isinstance(item, (str, int, float, bool)))
        ):
            if isinstance(item, str) and len(item) > 2000:
                raise refs.ReferenceError("참조 속성값이 너무 깁니다.")
            if isinstance(item, float) and not math.isfinite(item):
                raise refs.ReferenceError("참조 속성에 유한하지 않은 숫자가 있습니다.")
            result[key] = item
    return result


def select(target, candidates, payload):
    matched = []
    seen = set()
    for number, feature in enumerate(candidates):
        if number >= MAX_CANDIDATES:
            raise refs.ReferenceError(
                "조회 후보가 너무 많습니다. 작업 영역을 줄이세요."
            )
        try:
            shape = GEOSGeometry(json.dumps(feature["geometry"]), srid=4326)
            if shape.empty or not shape.valid:
                raise ValueError
            if not target.intersects(shape):
                continue
            item_id = str(feature.get("id", number))
            if item_id in seen:
                raise ValueError
            seen.add(item_id)
            matched.append(
                {"id": item_id, "properties": scalar_properties(feature["properties"])}
            )
        except (ValueError, TypeError, KeyError, GEOSException):
            raise refs.ReferenceError(
                "참조 도형 또는 식별자를 확인하지 못했습니다."
            ) from None
    matched.sort(key=lambda x: x["id"])
    policy = payload.get("selection", "unique")
    if policy not in ("unique", "all", "selected"):
        raise refs.ReferenceError("유일값·전체·직접 선택 중 하나를 지정하세요.")
    chosen = matched
    if policy == "selected":
        chosen = [row for row in matched if row["id"] == payload.get("chosen_id")]
        if len(chosen) != 1:
            raise refs.ReferenceError("현재 공간중첩 후보 중 하나를 선택하세요.")
    elif policy == "unique" and len(matched) > 1:
        chosen = []
    fields = payload.get("fields", [])
    if (
        not isinstance(fields, list)
        or len(fields) > 20
        or any(not isinstance(f, str) or len(f) > 150 for f in fields)
    ):
        raise refs.ReferenceError("가져올 필드를 최대 20개까지 선택하세요.")
    values = {}
    for field in fields:
        if chosen and any(field not in row["properties"] for row in chosen):
            raise refs.ReferenceError("선택한 필드가 참조자료에 없습니다.")
        values[field] = []
        for row in chosen:
            value = row["properties"].get(field)
            if value is not None and value not in values[field]:
                values[field].append(value)
    return {
        "status": "AMBIGUOUS"
        if policy == "unique" and len(matched) > 1
        else "READY"
        if chosen
        else "NO_MATCH",
        "candidates": matched,
        "values": values,
        "selection": policy,
        "fields": sorted({key for row in matched for key in row["properties"]}),
        "written": False,
    }


def dataset(cur, dataset_id, version_id=None):
    cur.execute(
        "SELECT d.id,d.name,d.kind,d.source_id,s.kind AS source_kind,s.url,s.enabled AS source_enabled "
        "FROM gis.reference_dataset d LEFT JOIN gis.reference_source s ON s.id=d.source_id "
        "WHERE d.id=%s AND d.enabled=true",
        [refs.identifier(dataset_id)],
    )
    result = refs.rows(cur)
    if not result or (result[0]["source_id"] and not result[0]["source_enabled"]):
        raise refs.ReferenceError("사용 가능한 참조자료를 찾을 수 없습니다.")
    item = result[0]
    if version_id:
        cur.execute(
            "SELECT id,label,filename,size_bytes,sha256,object_key,declared_crs FROM gis.reference_version "
            "WHERE id=%s AND dataset_id=%s AND status='stored'",
            [refs.identifier(version_id), item["id"]],
        )
        versions = refs.rows(cur)
        if not versions:
            raise refs.ReferenceError("해당 자료의 저장된 원본 버전을 선택하세요.")
        item["version"] = versions[0]
    return item


def vectors(root):
    result = []
    for path in sorted(Path(root).rglob("*")):
        if path.suffix.lower() not in {".shp", ".gpkg", ".geojson"}:
            continue
        try:
            source = DataSource(str(path))
            if str(source.driver) not in {"ESRI Shapefile", "GPKG", "GeoJSON"}:
                raise refs.ReferenceError("지원하지 않는 공간자료 드라이버입니다.")
            for layer in source:
                result.append((str(path.relative_to(root)) + "::" + layer.name, layer))
                if len(result) > 30:
                    raise refs.ReferenceError(
                        "레이어가 너무 많습니다. 원본을 나누세요."
                    )
        except (GDALException, ValueError):
            raise refs.ReferenceError(
                "공간 원본을 읽지 못했습니다. SHP·GPKG·GeoJSON을 확인하세요."
            ) from None
    return result


def table_rows(root, layer):
    path = Path(root) / layer
    if not path.resolve().is_relative_to(Path(root).resolve()) or not path.is_file():
        raise refs.ReferenceError("좌표 목록 파일을 확인하세요.")
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames or []
            if (
                not headers
                or len(headers) > 200
                or len(set(headers)) != len(headers)
                or any(not h for h in headers)
            ):
                raise refs.ReferenceError(
                    "CSV 첫 행에는 200개 이하의 중복 없는 필드명이 필요합니다."
                )
            for row in reader:
                if None in row:
                    raise refs.ReferenceError("CSV 행의 열 수가 첫 행과 다릅니다.")
                yield row
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        with path.open("rb") as stream:
            files.inspect_zip(stream, xlsx=True)
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            if book.active.max_column > 200 or book.active.max_row > 50001:
                raise refs.ReferenceError("좌표 목록은 200열·50,000행 이하로 나누세요.")
            rows = book.active.iter_rows(values_only=True)
            headers = next(rows, ())
            if any(not isinstance(h, str) or not h for h in headers) or len(
                set(headers)
            ) != len(headers):
                raise refs.ReferenceError(
                    "Excel 첫 행에는 중복 없는 필드명이 필요합니다."
                )
            for row in rows:
                if any(v is not None for v in row):
                    yield dict(zip(headers, row))
        finally:
            book.close()
    else:
        raise refs.ReferenceError("좌표 목록은 CSV 또는 XLSX를 선택하세요.")


def inspect_file(item):
    with files.local_original(item["version"]) as root:
        layers = [
            {
                "name": name,
                "fields": list(layer.fields),
                "crs": str(layer.srs) if layer.srs else "",
                "kind": "vector",
            }
            for name, layer in vectors(root)
        ]
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() in {".csv", ".xlsx"}:
                name = str(path.relative_to(root))
                first = next(table_rows(root, name), {})
                layers.append(
                    {
                        "name": name,
                        "fields": list(first),
                        "kind": "xy",
                        "crs": item["version"]["declared_crs"],
                    }
                )
        if not layers:
            raise refs.ReferenceError(
                "조회할 공간 레이어나 좌표 목록이 없습니다. PDF는 원본 열람으로 사용하세요."
            )
        return layers


def file_features(item, target, payload):
    with files.local_original(item["version"]) as root:
        selected = payload.get("layer")
        if not isinstance(selected, str) or len(selected) > 300:
            raise refs.ReferenceError("원본의 레이어를 선택하세요.")
        layers = dict(vectors(root))
        if selected in layers:
            layer = layers[selected]
            if not layer.srs:
                raise refs.ReferenceError(
                    "원본 레이어의 좌표계가 없습니다. 좌표계를 지정한 원본을 등록하세요."
                )
            filter_shape = target.clone()
            filter_shape.transform(layer.srs)
            layer.spatial_filter = filter_shape.extent
            for number, feature in enumerate(layer):
                if number >= MAX_CANDIDATES:
                    raise refs.ReferenceError("공간조회 후보가 너무 많습니다.")
                shape = feature.geom
                if shape is None:
                    raise refs.ReferenceError(
                        "참조 레이어에 도형이 없는 객체가 있습니다."
                    )
                shape.transform(4326)
                yield {
                    "id": str(feature.fid),
                    "geometry": json.loads(shape.json),
                    "properties": {field: feature.get(field) for field in layer.fields},
                }
        else:
            xfield, yfield, crs = (
                payload.get("x_field"),
                payload.get("y_field"),
                payload.get("reference_crs") or item["version"]["declared_crs"],
            )
            if (
                not isinstance(xfield, str)
                or not isinstance(yfield, str)
                or not xfield
                or not yfield
                or not isinstance(crs, str)
                or not re.fullmatch(r"EPSG:[1-9][0-9]{2,5}", crs)
            ):
                raise refs.ReferenceError(
                    "좌표 목록의 X·Y 필드와 EPSG 좌표계를 지정하세요."
                )
            for number, row in enumerate(table_rows(root, selected)):
                if number >= 50000:
                    raise refs.ReferenceError("좌표 목록은 50,000행 이하로 나누세요.")
                try:
                    x, y = float(row[xfield]), float(row[yfield])
                    if not math.isfinite(x) or not math.isfinite(y):
                        raise ValueError
                    shape = Point(x, y, srid=int(crs.removeprefix("EPSG:")))
                    shape.transform(4326)
                except (ValueError, TypeError, KeyError, GDALException):
                    raise refs.ReferenceError(
                        f"좌표 목록 {number + 2}행의 X·Y·좌표계를 확인하세요."
                    ) from None
                # No nearest-point inference: only actual overlap is returned.
                if target.intersects(shape):
                    yield {
                        "id": str(number + 2),
                        "geometry": json.loads(shape.geojson),
                        "properties": row,
                    }


def lookup(cur, payload):
    if not isinstance(payload, dict):
        raise refs.ReferenceError("요청은 객체여야 합니다.")
    target = geometry(payload.get("geometry"), payload.get("crs", "EPSG:4326"))
    item = dataset(cur, payload.get("dataset_id"), payload.get("version_id"))
    if "version" in item:
        result = select(target, file_features(item, target, payload), payload)
        lineage = {
            "dataset_id": str(item["id"]),
            "version_id": str(item["version"]["id"]),
            "sha256": item["version"]["sha256"],
        }
    else:
        service = payload.get("service")
        if (
            not isinstance(service, str)
            or service not in vworld.SERVICES
            or item["source_kind"] != "api"
            or item["url"] != vworld.ENDPOINT
            or item["kind"] != vworld.SERVICES[service]["kind"]
        ):
            raise refs.ReferenceError(
                "자료 종류와 브이월드 연결·서비스를 확인하세요. 파일 자료는 원본 버전이 필요합니다."
            )
        key, domain = vworld.credential(cur)
        result = select(target, vworld.features(service, target, key, domain), payload)
        lineage = {
            "dataset_id": str(item["id"]),
            "provider": "vworld",
            "service": service,
        }
    return {**result, "reference": lineage}
