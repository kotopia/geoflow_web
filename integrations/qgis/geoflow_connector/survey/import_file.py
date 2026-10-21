"""Local file mapping; source values are never reprojected or UUID-matched here."""
import csv
import math
import re
from pathlib import Path
from uuid import UUID, uuid4

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr")


class SourceRow(dict):
    """Preserve the physical row number even when blank rows are skipped."""
    def __init__(self, values, number):
        super().__init__(values)
        self.number = number


def sheet_names(path):
    path = Path(path)
    if path.suffix.lower() == ".xls":
        import xlrd
        return list(xlrd.open_workbook(str(path), on_demand=True).sheet_names())
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True)
    try:
        return list(book.sheetnames)
    finally:
        book.close()


def detect_csv_encoding(path, candidates=CSV_ENCODINGS):
    """Return the first strict decoder; never replace undecodable bytes."""
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf") and "utf-8-sig" in candidates:
        return "utf-8-sig"
    ordered = [encoding for encoding in ("utf-8", "cp949", "euc-kr")
               if encoding in candidates]
    ordered.extend(encoding for encoding in candidates if encoding not in ordered
                   and encoding != "utf-8-sig")
    for encoding in ordered:
        try:
            data.decode(encoding, errors="strict")
            return encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 인코딩을 자동 판정하지 못했습니다. 인코딩을 직접 선택하세요.")


def read_table(path, *, encoding="auto", delimiter=",", sheet=None,
               return_metadata=False):
    path = Path(path)
    metadata = {"encoding": None, "sheet": sheet}
    if path.suffix.lower() == ".csv":
        if encoding in (None, "", "auto"):
            encoding = detect_csv_encoding(path)
        metadata["encoding"] = encoding
        with path.open(encoding=encoding, newline="") as stream:
            rows = list(csv.reader(stream, delimiter=delimiter))
    elif path.suffix.lower() == ".xls":
        try:
            import xlrd
        except ImportError:
            raise ValueError("XLS 읽기에 필요한 xlrd가 QGIS Python 환경에 없습니다.") from None
        book = xlrd.open_workbook(str(path), on_demand=True)
        try:
            if sheet is None and book.nsheets != 1:
                raise ValueError("여러 시트가 있습니다. 시트 이름을 지정하세요: " + ", ".join(book.sheet_names()))
            page = book.sheet_by_name(sheet) if sheet else book.sheet_by_index(0)
            metadata["sheet"] = page.name
            rows = [page.row_values(index) for index in range(page.nrows)]
        finally:
            book.release_resources()
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=False)
        cached = None
        try:
            cached = load_workbook(path, read_only=True, data_only=True)
            if sheet is None and len(book.sheetnames) != 1:
                raise ValueError("여러 시트가 있습니다. 시트 이름을 지정하세요: " + ", ".join(book.sheetnames))
            page = book[sheet] if sheet else book[book.sheetnames[0]]
            rows = []
            for cells, values in zip(page.iter_rows(), cached[page.title].iter_rows()):
                row = []
                for cell, value in zip(cells, values):
                    if cell.data_type == "f" and value.value is None:
                        raise ValueError(f"{cell.row}행 · {cell.coordinate}: 수식 계산 결과가 없습니다. Excel에서 계산·저장하거나 값으로 변환하세요.")
                    if value.data_type == "e":
                        raise ValueError(f"{cell.row}행 · {cell.coordinate}: 셀 오류 값 {value.value!r}")
                    row.append(value.value)
                rows.append(row)
        finally:
            book.close()
            if cached is not None:
                cached.close()
    else:
        raise ValueError("CSV, XLS 또는 XLSX 파일을 선택하세요.")
    if not rows:
        raise ValueError("빈 파일입니다.")
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    if not all(headers) or len(set(headers)) != len(headers):
        raise ValueError("첫 행의 열 이름은 비어 있지 않고 고유해야 합니다.")
    result = []
    for number, row in enumerate(rows[1:], 2):
        if all(value is None or str(value).strip() == "" for value in row):
            continue
        if len(row) > len(headers):
            raise ValueError(f"{number}행: 헤더보다 열이 많습니다.")
        result.append(SourceRow(zip(headers, list(row) + [None] * (len(headers) - len(row))), number))
    if not result:
        raise ValueError("측량 데이터 행이 없습니다.")
    output = (headers, result, metadata) if return_metadata else (headers, result)
    return output


_DMS = re.compile(
    r"^\s*([NSEW])?\s*([+-]?\d+(?:\.\d+)?)"
    r"(?:\s*(?:°|-|\s)\s*(\d+(?:\.\d+)?))?"
    r"(?:\s*(?:['′’]|-|\s)\s*(\d+(?:\.\d+)?))?"
    r"\s*(?:[\"″”])?\s*([NSEW])?\s*$",
    re.IGNORECASE,
)


def parse_angle(value, *, latitude=False):
    """Parse decimal degrees or DMS without inferring missing/invalid parts."""
    if isinstance(value, bool) or value is None:
        raise ValueError("좌표값이 비어 있습니다.")
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        match = _DMS.fullmatch(str(value).strip())
        if not match:
            raise ValueError("지원하는 decimal/DMS 형식이 아닙니다.")
        prefix, degree, minute, second, suffix = match.groups()
        if prefix and suffix and prefix.upper() != suffix.upper():
            raise ValueError("방위 문자가 서로 다릅니다.")
        minute = float(minute or 0)
        second = float(second or 0)
        if minute >= 60 or second >= 60:
            raise ValueError("분/초는 60보다 작아야 합니다.")
        degree_value = float(degree)
        result = abs(degree_value) + minute / 60 + second / 3600
        direction = (prefix or suffix or "").upper()
        if direction in {"S", "W"} or degree_value < 0:
            result = -result
        if latitude and direction in {"E", "W"}:
            raise ValueError("위도에는 E/W를 사용할 수 없습니다.")
        if not latitude and direction in {"N", "S"}:
            raise ValueError("경도에는 N/S를 사용할 수 없습니다.")
    limit = 90 if latitude else 180
    if not math.isfinite(result) or not -limit <= result <= limit:
        raise ValueError(f"허용 범위 {-limit}~{limit}도를 벗어났습니다.")
    return result


def suggest_columns(headers, *, geographic=False):
    """Suggest mappings only from explicit, normalized column names."""
    aliases = {
        "source_row_id": ("이름", "점번호", "측점번호", "측점명", "name", "point", "point_id", "id"),
        "raw_code": ("코드", "code", "raw_code"),
        # Bare X/Y are intentionally excluded. Survey equipment may export
        # X=Northing and Y=Easting, while the server contract expects
        # raw_x=Easting and raw_y=Northing.
        "raw_x": ("e", "east", "easting", "x(e)", "동쪽좌표"),
        "raw_y": ("n", "north", "northing", "y(n)", "북쪽좌표"),
        "longitude": ("longitude", "lon", "경도"),
        "latitude": ("latitude", "lat", "위도"),
        "raw_z": ("z", "z(레벨)", "고도", "표고", "elevation", "level"),
    }
    normalized = {str(header).strip().casefold(): header for header in headers}
    keys = ("source_row_id", "raw_code", "longitude", "latitude", "raw_z") if geographic else (
        "source_row_id", "raw_code", "raw_x", "raw_y", "raw_z")
    return {key: next((normalized[name.casefold()] for name in aliases[key]
                       if name.casefold() in normalized), None) for key in keys}


def build_import(rows, mapping, *, original_file_name, source_type,
                 survey_type=None, source_crs="", target_crs="",
                 geoid_model="", calibration_info=None, geographic=False,
                 source_id=None, source_group_id=None, supersedes_id=None):
    if source_type not in {"GNSS", "GPS", "TOTAL", "CSV", "XLSX", "OTHER"}:
        raise ValueError("지원하지 않는 source_type입니다.")
    if survey_type is not None and survey_type not in {"GNSS", "TOTAL_STATION"}:
        raise ValueError("지원하지 않는 survey_type입니다.")
    if not geographic and not source_crs.strip():
        raise ValueError("TM 입력에는 source_crs를 직접 지정하세요. EPSG를 추정하지 않습니다.")
    if source_crs.strip() and not re.fullmatch(r"EPSG:[1-9][0-9]*", source_crs.strip()):
        raise ValueError("원본 좌표계는 EPSG 코드가 있는 좌표계를 선택하세요.")
    if target_crs.strip() and not re.fullmatch(r"EPSG:[1-9][0-9]*", target_crs.strip()):
        raise ValueError("대상 좌표계는 EPSG 코드가 있는 좌표계여야 합니다.")
    if not isinstance(calibration_info if calibration_info is not None else {}, dict):
        raise ValueError("calibration_info는 JSON object여야 합니다.")
    if (source_group_id is None) != (supersedes_id is None):
        raise ValueError("개정에는 source_group_id와 supersedes_id가 모두 필요합니다.")
    coordinate_fields = ("longitude", "latitude") if geographic else ("raw_x", "raw_y")
    allowed = {"source_row_id", "raw_code", "raw_z", *coordinate_fields}
    if set(mapping) - allowed:
        raise ValueError("contract에 정의된 입력 컬럼만 매핑할 수 있습니다.")
    for field in ("source_row_id", *coordinate_fields):
        if not mapping.get(field):
            raise ValueError(f"{field} 열을 선택하세요.")
    points, identifiers = [], set()
    for number, row in enumerate(rows, 2):
        number = getattr(row, "number", number)
        raw_id = row[mapping["source_row_id"]]
        identifier = "" if raw_id is None else str(raw_id).strip()
        if not identifier or identifier in identifiers:
            raise ValueError(f"{number}행 · source_row_id · 값 {raw_id!r}: 비었거나 중복입니다.")
        identifiers.add(identifier)
        point = {"source_row_id": identifier}
        raw_code_column = mapping.get("raw_code")
        if raw_code_column and row[raw_code_column] is not None:
            raw_code = str(row[raw_code_column]).strip()
            if raw_code:
                point["raw_code"] = raw_code
        for field in (*coordinate_fields, "raw_z"):
            column = mapping.get(field)
            if not column:
                continue
            value = row[column]
            if field == "raw_z" and (value is None or str(value).strip() == ""):
                continue
            try:
                if isinstance(value, bool):
                    raise ValueError()
                if field in {"longitude", "latitude"}:
                    # DMS normalization must happen before any float-only
                    # validation so Unicode prime/double-prime input survives.
                    value = parse_angle(value, latitude=field == "latitude")
                else:
                    value = float(value)
                if not math.isfinite(value):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError(f"{number}행 · {field} · 값 {row[column]!r}: 유한한 숫자가 아닙니다.") from None
            point[field] = value
        if geographic and not (-180 <= point["longitude"] <= 180 and -90 <= point["latitude"] <= 90):
            raise ValueError(f"{number}행 · longitude/latitude · 값 {point['longitude']}/{point['latitude']}: 경위도 범위를 벗어났습니다.")
        if geographic:
            # Preserve the source columns as immutable evidence as well as the
            # normalized geographic input. The server remains responsible for
            # deriving project x/y and authoritative longitude/latitude.
            point["raw_x"] = point["longitude"]
            point["raw_y"] = point["latitude"]
            point["raw_crs"] = "EPSG:4326"
        points.append(point)
    if not points:
        raise ValueError("측량 데이터 행이 없습니다.")
    payload = {"id": str(UUID(str(source_id))) if source_id else str(uuid4()),
               "source_type": source_type, "original_file_name": original_file_name,
               "calibration_info": calibration_info or {}, "points": points}
    if survey_type is not None:
        payload["survey_type"] = survey_type
    if source_crs.strip():
        payload["source_crs"] = source_crs.strip()
    if geoid_model.strip():
        payload["geoid_model"] = geoid_model.strip()
    if target_crs.strip():
        payload["target_crs"] = target_crs.strip()
    if source_group_id is not None:
        payload.update(source_group_id=str(UUID(str(source_group_id))),
                       supersedes_id=str(UUID(str(supersedes_id))))
    return payload
