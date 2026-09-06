from __future__ import annotations

import math
from dataclasses import dataclass


WEB_MERCATOR_RADIUS = 6_378_137.0
WEB_MERCATOR_LAT_LIMIT = 85.05112878
DEFAULT_CELL_SIZE_M = 250
DEFAULT_ACTIVE_RADIUS_M = 300
DEFAULT_PREFETCH_RADIUS_M = 750
DEFAULT_MOVEMENT_THRESHOLD_M = 100
DEFAULT_MAX_CELLS = 192
MIN_CELL_SIZE_M = 100
MAX_CELL_SIZE_M = 2_000
MAX_PLAN_CELLS = 512


@dataclass(frozen=True)
class RoamingCell:
    key: str
    priority: str
    bbox: tuple[float, float, float, float]
    distance_m: float


def _clamp_latitude(latitude: float) -> float:
    return max(-WEB_MERCATOR_LAT_LIMIT, min(WEB_MERCATOR_LAT_LIMIT, float(latitude)))


def lonlat_to_web_mercator(longitude: float, latitude: float) -> tuple[float, float]:
    lon = float(longitude)
    lat = _clamp_latitude(latitude)
    if not -180.0 <= lon <= 180.0:
        raise ValueError("longitude must be between -180 and 180")
    x = WEB_MERCATOR_RADIUS * math.radians(lon)
    y = WEB_MERCATOR_RADIUS * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


def web_mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = math.degrees(float(x) / WEB_MERCATOR_RADIUS)
    lat = math.degrees(2.0 * math.atan(math.exp(float(y) / WEB_MERCATOR_RADIUS)) - math.pi / 2.0)
    return lon, _clamp_latitude(lat)


def validate_cell_size(value: int | float) -> int:
    size = int(value)
    if size < MIN_CELL_SIZE_M or size > MAX_CELL_SIZE_M:
        raise ValueError(
            f"cell_size_m must be between {MIN_CELL_SIZE_M} and {MAX_CELL_SIZE_M}"
        )
    return size


def cell_key(cell_size_m: int, ix: int, iy: int) -> str:
    size = validate_cell_size(cell_size_m)
    return f"{size}:{int(ix)}:{int(iy)}"


def parse_cell_key(value: str) -> tuple[int, int, int]:
    parts = str(value or "").split(":")
    if len(parts) != 3:
        raise ValueError("cell must be cell_size_m:ix:iy")
    try:
        size, ix, iy = (int(part) for part in parts)
    except (TypeError, ValueError) as exc:
        raise ValueError("cell must contain integer cell_size_m, ix and iy") from exc
    return validate_cell_size(size), ix, iy


def cell_bbox(cell_size_m: int, ix: int, iy: int) -> tuple[float, float, float, float]:
    size = validate_cell_size(cell_size_m)
    minx = int(ix) * size
    miny = int(iy) * size
    maxx = minx + size
    maxy = miny + size
    min_lon, min_lat = web_mercator_to_lonlat(minx, miny)
    max_lon, max_lat = web_mercator_to_lonlat(maxx, maxy)
    return min_lon, min_lat, max_lon, max_lat


def _indices_for_xy_bbox(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    cell_size_m: int,
):
    size = validate_cell_size(cell_size_m)
    start_x = math.floor(minx / size)
    end_x = math.floor(math.nextafter(maxx, minx) / size)
    start_y = math.floor(miny / size)
    end_y = math.floor(math.nextafter(maxy, miny) / size)
    for ix in range(start_x, end_x + 1):
        for iy in range(start_y, end_y + 1):
            yield ix, iy


def _cell_distance_to_point_m(
    *,
    cell_size_m: int,
    ix: int,
    iy: int,
    x: float,
    y: float,
) -> float:
    size = validate_cell_size(cell_size_m)
    minx = ix * size
    miny = iy * size
    maxx = minx + size
    maxy = miny + size
    nearest_x = min(max(x, minx), maxx)
    nearest_y = min(max(y, miny), maxy)
    return math.hypot(x - nearest_x, y - nearest_y)


def _cell_center_distance_m(
    *,
    cell_size_m: int,
    ix: int,
    iy: int,
    x: float,
    y: float,
) -> float:
    size = validate_cell_size(cell_size_m)
    cx = (ix + 0.5) * size
    cy = (iy + 0.5) * size
    return math.hypot(cx - x, cy - y)


def _priority_rank(value: str) -> int:
    return {"active": 0, "viewport": 1, "prefetch": 2}.get(str(value), 9)


def plan_roaming_cells(
    *,
    longitude: float | None = None,
    latitude: float | None = None,
    viewport_bbox: tuple[float, float, float, float] | None = None,
    cell_size_m: int = DEFAULT_CELL_SIZE_M,
    active_radius_m: int = DEFAULT_ACTIVE_RADIUS_M,
    prefetch_radius_m: int = DEFAULT_PREFETCH_RADIUS_M,
    known_cells: set[str] | None = None,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> dict:
    size = validate_cell_size(cell_size_m)
    active_radius = int(active_radius_m)
    prefetch_radius = int(prefetch_radius_m)
    max_count = min(MAX_PLAN_CELLS, max(1, int(max_cells)))
    if active_radius < 0:
        raise ValueError("active_radius_m must be >= 0")
    if prefetch_radius < active_radius:
        raise ValueError("prefetch_radius_m must be >= active_radius_m")
    if prefetch_radius > 10_000:
        raise ValueError("prefetch_radius_m must be <= 10000")

    has_position = longitude is not None or latitude is not None
    if has_position and (longitude is None or latitude is None):
        raise ValueError("longitude and latitude must be supplied together")
    if not has_position and viewport_bbox is None:
        raise ValueError("GPS position or viewport_bbox is required")

    gps_xy = None
    if has_position:
        gps_xy = lonlat_to_web_mercator(float(longitude), float(latitude))

    viewport_xy = None
    if viewport_bbox is not None:
        min_lon, min_lat, max_lon, max_lat = (float(value) for value in viewport_bbox)
        if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError("viewport_bbox is outside EPSG:4326 bounds or invalid")
        vx1, vy1 = lonlat_to_web_mercator(min_lon, min_lat)
        vx2, vy2 = lonlat_to_web_mercator(max_lon, max_lat)
        viewport_xy = (min(vx1, vx2), min(vy1, vy2), max(vx1, vx2), max(vy1, vy2))

    candidates: dict[str, tuple[str, float, int, int]] = {}

    if gps_xy is not None:
        gx, gy = gps_xy
        for ix, iy in _indices_for_xy_bbox(
            gx - prefetch_radius,
            gy - prefetch_radius,
            gx + prefetch_radius,
            gy + prefetch_radius,
            size,
        ):
            edge_distance = _cell_distance_to_point_m(
                cell_size_m=size,
                ix=ix,
                iy=iy,
                x=gx,
                y=gy,
            )
            if edge_distance > prefetch_radius:
                continue
            priority = "active" if edge_distance <= active_radius else "prefetch"
            key = cell_key(size, ix, iy)
            candidates[key] = (
                priority,
                _cell_center_distance_m(
                    cell_size_m=size,
                    ix=ix,
                    iy=iy,
                    x=gx,
                    y=gy,
                ),
                ix,
                iy,
            )

    if viewport_xy is not None:
        vminx, vminy, vmaxx, vmaxy = viewport_xy
        vcx = (vminx + vmaxx) / 2.0
        vcy = (vminy + vmaxy) / 2.0
        for ix, iy in _indices_for_xy_bbox(vminx, vminy, vmaxx, vmaxy, size):
            key = cell_key(size, ix, iy)
            existing = candidates.get(key)
            distance = _cell_center_distance_m(
                cell_size_m=size,
                ix=ix,
                iy=iy,
                x=vcx,
                y=vcy,
            )
            if existing is None:
                candidates[key] = ("viewport", distance, ix, iy)
            elif _priority_rank(existing[0]) > _priority_rank("viewport"):
                candidates[key] = ("viewport", min(existing[1], distance), ix, iy)

    known = {str(value) for value in (known_cells or set()) if value}
    ordered = sorted(
        (
            (key, priority, distance, ix, iy)
            for key, (priority, distance, ix, iy) in candidates.items()
            if key not in known
        ),
        key=lambda row: (_priority_rank(row[1]), row[2], row[0]),
    )
    truncated = len(ordered) > max_count
    ordered = ordered[:max_count]
    cells = [
        RoamingCell(
            key=key,
            priority=priority,
            bbox=cell_bbox(size, ix, iy),
            distance_m=round(float(distance), 3),
        )
        for key, priority, distance, ix, iy in ordered
    ]
    return {
        "cell_size_m": size,
        "active_radius_m": active_radius,
        "prefetch_radius_m": prefetch_radius,
        "movement_threshold_m": DEFAULT_MOVEMENT_THRESHOLD_M,
        "known_count": len(known),
        "candidate_count": len(candidates),
        "returned": len(cells),
        "truncated": truncated,
        "cells": cells,
    }
