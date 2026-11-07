"""QGIS geometry adapter. Reference layers are explicitly bound by QGIS layer ID."""
from math import atan2, degrees, isfinite
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException,
    QgsGeometry, QgsPointXY, QgsProject, QgsSpatialIndex, QgsWkbTypes, Qgis,
)


class Spatial:
    def __init__(self, layer):
        self.layer = layer
        self.crs = layer.crs()
        self.project = QgsProject.instance()
        self.references = {}
        self.aggregates = {}
        self.aggregate_searches = 0

    @staticmethod
    def exists(geom):
        return geom is not None and not geom.isEmpty()

    def valid(self, geom):
        return self.exists(geom) and geom.isGeosValid()

    def geometry_type(self, geom):
        return QgsWkbTypes.displayString(QgsWkbTypes.flatType(geom.wkbType())).upper() if self.exists(geom) else None

    def geometry_key(self, geom):
        if not self.exists(geom):
            return None
        copy = QgsGeometry(geom)
        copy.normalize()
        return bytes(copy.asWkb())

    @staticmethod
    def transform(geom, source, dest, project):
        if not source.isValid() or not dest.isValid():
            raise ValueError("유효한 CRS 필요")
        g = QgsGeometry(geom)
        try:
            if source != dest and g.transform(QgsCoordinateTransform(source, dest, project)) != Qgis.GeometryOperationResult.Success:
                raise ValueError("좌표 변환 실패")
        except QgsCsException as exc:
            raise ValueError("좌표 변환 실패") from exc
        return g

    def metric(self, params):
        crs = QgsCoordinateReferenceSystem(params["crs"])
        if not crs.isValid() or crs.isGeographic() or crs.mapUnits() != Qgis.DistanceUnit.Meters:
            raise ValueError("미터 단위 투영 CRS 필요")
        return crs

    def line(self, geom):
        if self.geometry_type(geom) not in {"LINESTRING", "MULTILINESTRING"}:
            raise ValueError("선형 도형 필요")
        if geom.isMultipart():
            parts = geom.asMultiPolyline()
            if len(parts) != 1:
                raise ValueError("여러 파트의 시점·종점 모호")
            points = parts[0]
        else:
            points = geom.asPolyline()
        if len(points) < 2:
            raise ValueError("유효한 선분 없음")
        return points

    def measure(self, geom, params, kind):
        if not self.valid(geom):
            raise ValueError("유효한 도형 필요")
        g = self.transform(geom, self.crs, self.metric(params), self.project)
        if kind == "ANGLE":
            pts = self.line(g)
            segments = list(zip(pts, pts[1:]))
            if params.get("position", "start") == "end":
                segments.reverse()
            for a,b in segments:
                if a != b:
                    return degrees(atan2(b.y()-a.y(), b.x()-a.x())) % 360
            raise ValueError("길이 0인 선분")
        allowed = {"LENGTH": {"m":1, "km":1000}, "AREA": {"m2":1, "ha":10000}}
        if kind == "LENGTH" and g.type() != Qgis.GeometryType.Line:
            raise ValueError("길이 계산에는 선형 도형 필요")
        if kind == "AREA" and g.type() != Qgis.GeometryType.Polygon:
            raise ValueError("면적 계산에는 면 도형 필요")
        value = g.length() if kind == "LENGTH" else g.area()
        return value / allowed[kind][params["unit"]]

    def validate_aggregate(self, params):
        from qgis.core import QgsVectorLayer
        from .catalog import validate_operation
        validate_operation('AGGREGATE', params)
        self.metric(params)
        ref = self.project.mapLayer(params['reference_layer'])
        if not isinstance(ref, QgsVectorLayer) or not ref.isValid():
            raise ValueError('지정한 심도 원본 레이어가 없습니다.')
        if params.get('reference_binding'):
            import hashlib
            current = dict(definition_layer_id=str(ref.customProperty('geoflow/definition_layer_id', '')),
                           provider=ref.providerType(), source_sha256=hashlib.sha256(ref.source().encode()).hexdigest())
            if current != params['reference_binding']:
                raise ValueError('심도 원본 연결 정보가 변경되었습니다. 원본 레이어를 다시 지정하세요.')
        index = ref.fields().indexFromName(params['reference_field'])
        if index < 0 or not ref.fields()[index].isNumeric():
            raise ValueError('지정한 심도 필드는 숫자형이어야 합니다.')
        if not ref.crs().isValid() or not self.crs.isValid():
            raise ValueError('원본/참조 좌표계가 필요합니다.')
        if ref.id() == self.layer.id():
            raise ValueError('별도의 저장 심도 원본 레이어를 지정하세요.')
        for key in params.get('candidate_filter', {}):
            if ref.fields().indexFromName(key) < 0:
                raise ValueError(f'참조 범위 필드 없음: {key}')
        for key in params.get('target_filter', {}):
            if self.layer.fields().indexFromName(key) < 0:
                raise ValueError(f'관로 범위 필드 없음: {key}')

    def aggregate(self, geom, params):
        """Assign stored reference objects to unambiguous pipes once per shared group."""
        import json
        from .ui_values import scalar
        from .references import aggregate_values
        self.validate_aggregate(params)
        shared = {k: v for k, v in params.items() if k != 'statistic'}
        key = json.dumps(shared, sort_keys=True)
        if key not in self.aggregates:
            crs = self.metric(params)
            index, refs = self.reference(params, crs)
            ref_layer = self.project.mapLayer(params['reference_layer'])
            selected = set(ref_layer.selectedFeatureIds()) if params['scope'] == 'selected' else None
            # Both indices and statistics are shared by mean/minimum/maximum fields.
            pipes, groups, ambiguous = {}, {}, {}
            from qgis.core import QgsFeature
            pipe_index = QgsSpatialIndex()
            for feature in self.layer.getFeatures():
                if any(scalar(feature[k]) != v for k, v in params.get('target_filter', {}).items()):
                    continue
                if not self.valid(feature.geometry()):
                    continue
                g = self.transform(feature.geometry(), self.crs, crs, self.project)
                entry = QgsFeature(feature.id())
                entry.setGeometry(g)
                pipe_index.addFeature(entry)
                pipes[feature.id()] = (bytes(feature.geometry().asWkb()), g)
                groups[feature.id()], ambiguous[feature.id()] = [], []
            for fid, (feature, g) in refs.items():
                if selected is not None and fid not in selected:
                    continue
                if any(scalar(feature[k]) != v for k, v in params.get('candidate_filter', {}).items()):
                    continue
                bounds = g.boundingBox()
                bounds.grow(params['radius'])
                candidates = sorted((g.distance(pipes[i][1]), i) for i in set(pipe_index.intersects(bounds)))
                candidates = [(distance, i) for distance, i in candidates if 0 <= distance <= params['radius']]
                if not candidates:
                    continue
                if len(candidates) > 1 and (params['selection_policy'] == 'unique' or abs(candidates[0][0] - candidates[1][0]) <= 1e-8):
                    for _, i in candidates:
                        ambiguous[i].append(fid)
                    continue
                groups[candidates[0][1]].append((fid, scalar(feature[params['reference_field']])))
            results = {}
            for i, (wkb, _) in pipes.items():
                result = aggregate_values(groups[i])
                result.update(settings=shared, ambiguous=ambiguous[i], target_id=i,
                              reference_layer=ref_layer.id(), reference_field=params['reference_field'], target_wkb=wkb.hex())
                results[i] = result
            self.aggregates[key] = results
            self.aggregate_searches += 1
        results = self.aggregates[key]
        if hasattr(self, 'current_feature_id'):
            result = results.get(self.current_feature_id)
        else:
            matches = [r for r in results.values() if r['target_wkb'] == bytes(geom.asWkb()).hex()]
            if len(matches) > 1:
                raise ValueError('동일 위치 관로 후보가 여러 개입니다. 검토가 필요합니다.')
            result = matches[0] if matches else None
        if result is None:
            raise ValueError('관로 범위에서 제외되었거나 유효한 도형이 없습니다.')
        if result['ambiguous']:
            raise ValueError(f"복수 관로 후보: 원본 객체 {result['ambiguous']} · 검토 필요")
        return result

    def reference(self, params, crs):
        from qgis.core import QgsFeature, QgsVectorLayer
        lid = params["reference_layer"]
        key = lid, crs.authid()
        if key not in self.references:
            layer = self.project.mapLayer(lid)
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                raise ValueError("참조 레이어가 열려 있지 않음")
            index, features = QgsSpatialIndex(), {}
            for f in layer.getFeatures():
                if self.valid(f.geometry()):
                    geom = self.transform(f.geometry(), layer.crs(), crs, self.project)
                    entry = QgsFeature(f.id())
                    entry.setGeometry(geom)
                    index.addFeature(entry)
                    features[f.id()] = (f, geom)
            self.references[key] = index, features
        return self.references[key]

    def lookup(self, geom, params, kind, *, existence=False):
        from .ui_values import scalar
        if not self.valid(geom):
            raise ValueError("유효한 조회 도형 필요")
        crs = self.metric(params)
        g = self.transform(geom, self.crs, crs, self.project)
        if kind in {"START_REFERENCE", "END_REFERENCE"}:
            points = self.line(g)
            g = QgsGeometry.fromPointXY(QgsPointXY(points[0 if kind == "START_REFERENCE" else -1]))
        predicate = params.get("predicate", "within_radius")
        radius = params.get("radius", 0)
        if type(radius) not in {float, int} or not isfinite(radius) or radius < 0:
            raise ValueError("유효한 검색 반경 필요")
        index, items = self.reference(params, crs)
        bounds = g.boundingBox()
        if predicate == "within_radius":
            bounds.grow(radius)
        matches = []
        for fid in index.intersects(bounds):
            f, ref = items[fid]
            if any(scalar(f[k]) != v for k,v in params.get("candidate_filter", {}).items()):
                continue
            distance = g.distance(ref)
            if predicate == "intersects":
                valid = g.intersects(ref)
            elif predicate == "within":
                valid = g.within(ref)
            elif predicate == "within_radius":
                valid = 0 <= distance <= radius
            else:
                raise ValueError("지원하지 않는 공간 조건")
            if valid:
                matches.append((distance, fid, f))
        if existence:
            return bool(matches)
        if not matches:
            raise ValueError("참조 객체 없음")
        matches.sort(key=lambda x: (x[0],x[1]))
        policy = params.get("selection_policy", "unique")
        if policy not in {"unique", "nearest"}:
            raise ValueError("지원하지 않는 후보 선택 정책")
        if len(matches) > 1 and (policy == "unique" or abs(matches[0][0]-matches[1][0]) <= 1e-8):
            raise ValueError("복수 참조 후보")
        return scalar(matches[0][2][params["reference_field"]])
