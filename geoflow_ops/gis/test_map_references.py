"""Isolated DB-free map tests. No production settings, credentials or services."""
import json
import math
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY="isolated-map-tests", INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "control", "geoflow_ops"], DATABASES={"default": {"ENGINE": "django.db.backends.dummy"}}, USE_TZ=True, ALLOWED_HOSTS=["testserver"], ROOT_URLCONF=__name__, MIDDLEWARE=["django.middleware.csrf.CsrfViewMiddleware"], TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}])
    import django
    django.setup()
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import Client, RequestFactory, override_settings
from django.urls import path
from control.services import gis_reference_lookup as engine
from control.services import gis_reference_vworld as vworld
from control.services.gis_references import ReferenceError
from . import views, spatial_reference_views as api

urlpatterns = [path("area/", views.project_business_area, {"project_id": uuid4()}), path("overlay/", api.map_reference_overlay)]
POINT = {"type": "Point", "coordinates": [127, 36]}
BOX = {"type": "Polygon", "coordinates": [[[126.999,35.999],[127.001,35.999],[127.001,36.001],[126.999,36.001],[126.999,35.999]]]}

def request(payload=None, method="post"):
    value = RequestFactory().get("/") if method == "get" else RequestFactory().post("/", data=json.dumps(payload or {}), content_type="application/json")
    value.user = SimpleNamespace(is_authenticated=True)
    value.session = {}
    value._dont_enforce_csrf_checks = True
    return value

class TileTests(TestCase):
    def test_cadastral_uses_fixed_wms_and_computed_mercator_bbox(self):
        reader = MagicMock(return_value=b"\x89PNG\r\n\x1a\nfixture")
        data, mime = vworld.tile("Cadastral", 1, 0, 1, "fixture-key", "https://geoflow.co.kr", reader)
        parsed = urlsplit(reader.call_args.args[0]); params = parse_qs(parsed.query)
        self.assertEqual(parsed.hostname, "api.vworld.kr")
        self.assertEqual(parsed.path, "/req/wms")
        self.assertEqual(params["layers"], ["lt_c_landinfobasemap"])
        self.assertEqual(params["crs"], ["EPSG:3857"])
        self.assertEqual(params["transparent"], ["true"])
        self.assertEqual(list(map(float, params["bbox"][0].split(','))), [0,0,math.pi*6378137,math.pi*6378137])
        self.assertEqual(mime, "image/png")

    def test_satellite_uses_jpeg_and_hybrid_is_separate(self):
        reader = MagicMock(return_value=b"\xff\xd8\xfffixture")
        self.assertEqual(vworld.tile("Satellite",1,0,0,"fixture","https://geoflow.co.kr",reader)[1], "image/jpeg")
        self.assertIn("/Satellite/1/0/0.jpeg", reader.call_args.args[0])

    def test_bad_style_or_coordinates_never_contact_provider(self):
        reader = MagicMock()
        for style,z,y,x in [("arbitrary",1,0,0),("Cadastral",20,0,0),("Base",1,2,0)]:
            with self.assertRaises(ReferenceError): vworld.tile(style,z,y,x,"fixture","https://geoflow.co.kr",reader)
        reader.assert_not_called()

    def test_invalid_tile_never_reads_credential(self):
        with patch.object(api,"_map_context"), patch.object(vworld,"credential") as key:
            with self.assertRaises(Http404): api.tenant_reference_tile(request(method="get"),"Base",20,0,0)
            key.assert_not_called()

    def test_denied_tenant_and_project_never_read_secret(self):
        with patch.object(api,"_map_context",side_effect=PermissionDenied), patch.object(vworld,"credential") as key:
            for function,args in [(api.tenant_reference_tile,("Base",1,0,0)),(api.project_reference_tile,(uuid4(),"Base",1,0,0))]:
                with self.assertRaises(PermissionDenied): function(request(method="get"),*args)
            key.assert_not_called()

    def test_failed_provider_returns_no_secret_or_url(self):
        with patch.object(api,"_map_context"), patch.object(api,"connections",{"default":MagicMock()}), patch.object(vworld,"credential",return_value=("sensitive-fixture","https://geoflow.co.kr")), patch.object(vworld,"tile",side_effect=ReferenceError("sensitive-fixture")):
            result=api.tenant_reference_tile(request(method="get"),"Base",1,0,0)
            self.assertEqual(result.status_code,503)
            self.assertNotIn(b"sensitive",result.content)

class OverlayTests(TestCase):
    def setUp(self):
        self.item={"id":uuid4(),"version":{"id":uuid4(),"sha256":"fixture"}}
        self.guard=patch.object(api,"_map_context"); self.guard.start(); self.addCleanup(self.guard.stop)
        self.db=patch.object(api,"connections",{"default":MagicMock()}); self.db.start(); self.addCleanup(self.db.stop)
        self.dataset=patch.object(engine,"dataset",return_value=self.item); self.dataset.start(); self.addCleanup(self.dataset.stop)

    def test_overlay_returns_only_intersections_and_never_writes(self):
        candidates=[{"id":"one","geometry":POINT,"properties":{"번호":"001"}}, {"id":"two","geometry":{"type":"Point","coordinates":[128,37]},"properties":{}}]
        with patch.object(engine,"file_features",return_value=candidates):
            result=api.map_reference_overlay(request({"dataset_id":str(uuid4()),"version_id":str(uuid4()),"geometry":BOX}))
            body=json.loads(result.content)
            self.assertEqual([x["id"] for x in body["features"]],["one"])
            self.assertEqual(body["features"][0]["properties"]["번호"],"001")
            self.assertIs(body["written"],False)
            self.assertEqual(body["reference"]["sha256"],"fixture")

    def test_large_viewport_is_rejected_before_file_read(self):
        with patch.object(engine,"file_features") as read:
            result=api.map_reference_overlay(request({"version_id":str(uuid4()),"geometry":{"type":"Polygon","coordinates":[[[126,35],[128,35],[128,37],[126,37],[126,35]]]}}))
            self.assertEqual(result.status_code,400); read.assert_not_called()

    def test_inspect_needs_no_viewport(self):
        with patch.object(engine,"inspect_file",return_value=[{"name":"sheets","kind":"vector"}]):
            result=api.map_reference_overlay(request({"action":"inspect","version_id":str(uuid4())}))
            self.assertEqual(json.loads(result.content)["layers"][0]["name"],"sheets")

    def test_provider_or_disabled_dataset_errors_are_scrubbed(self):
        with patch.object(engine,"dataset",side_effect=ReferenceError("private-s3-location")):
            result=api.map_reference_overlay(request({"version_id":str(uuid4()),"geometry":BOX}))
            self.assertEqual(result.status_code,400); self.assertNotIn(b"private-s3",result.content)

    def test_permission_checked_before_file_access(self):
        with patch.object(api,"_map_context",side_effect=PermissionDenied), patch.object(engine,"file_features") as read:
            with self.assertRaises(PermissionDenied): api.map_reference_overlay(request(),uuid4())
            read.assert_not_called()

    @override_settings(ALLOWED_HOSTS=["testserver"], ROOT_URLCONF=__name__, MIDDLEWARE=["django.middleware.csrf.CsrfViewMiddleware"])
    def test_csrf_required(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/overlay/',data='{}',content_type='application/json').status_code,403)
        self.assertEqual(client.post('/area/',data='{}',content_type='application/json').status_code,403)

class BusinessAreaTests(TestCase):
    def test_missing_location_never_infers_from_other_fields(self):
        for extension in [None,{}, {"address":"Daejeon"}, {"map_center":[127,36]}]:
            self.assertIsNone(views._business_area(extension))

    def test_valid_point_polygon_and_multipolygon(self):
        for geometry in [POINT,BOX,{"type":"MultiPolygon","coordinates":[BOX["coordinates"]]}]:
            self.assertEqual(views._business_area({"gis_business_area":geometry})["type"],geometry["type"])

    def test_invalid_or_unbounded_geometry_is_unregistered(self):
        for geometry in [{"type":"LineString","coordinates":[[127,36],[128,37]]},{"type":"Point","coordinates":[200,36]}, {"type":"Point","coordinates":[127,float('nan')]}]:
            self.assertIsNone(views._business_area({"gis_business_area":geometry}))

    def test_area_write_preserves_other_project_extension_and_tenant(self):
        project=SimpleNamespace(id=uuid4(),ext={"other":"preserved"})
        manager=MagicMock(); manager.select_for_update.return_value.get.return_value=project
        with patch.object(views,"_require_gis_view",return_value="tenant-a"), patch.object(views,"_require_project_gis_access",return_value=(project,{})),patch.object(views,"gf_has_perm",return_value=True),patch.object(views,"project_access_policy") as policy,patch.object(views.Project.objects,"using",return_value=manager) as using,patch.object(views.transaction,"atomic",return_value=nullcontext()):
            policy.return_value.can_edit_project.return_value=True
            result=views.project_business_area(request({"geometry":POINT,"previous":None}),project.id)
            self.assertEqual(result.status_code,200)
            self.assertEqual(manager.filter.return_value.update.call_args.kwargs["ext"]["other"],"preserved")
            self.assertEqual(using.call_args.args,("tenant-a",))

    def test_stale_area_update_is_rejected(self):
        project=SimpleNamespace(id=uuid4(),ext={"gis_business_area":POINT})
        manager=MagicMock(); manager.select_for_update.return_value.get.return_value=project
        with patch.object(views,"_require_gis_view",return_value="tenant-a"),patch.object(views,"_require_project_gis_access",return_value=(project,{})),patch.object(views,"gf_has_perm",return_value=True),patch.object(views,"project_access_policy"),patch.object(views.Project.objects,"using",return_value=manager),patch.object(views.transaction,"atomic",return_value=nullcontext()):
            result=views.project_business_area(request({"geometry":None,"previous":None}),project.id)
            self.assertEqual(result.status_code,409); manager.filter.return_value.update.assert_not_called()

    def test_viewer_cannot_register_area(self):
        with patch.object(views,"_require_gis_view",return_value="tenant-a"),patch.object(views,"_require_project_gis_access",return_value=(SimpleNamespace(id=uuid4()),{})),patch.object(views,"gf_has_perm",return_value=False),patch.object(views.Project.objects,"using") as using:
            with self.assertRaises(PermissionDenied): views.project_business_area(request({"geometry":POINT,"previous":None}),uuid4())
            using.assert_not_called()

    def test_templates_compile(self):
        from django.template.loader import get_template
        get_template("geoflow_ops/gis/dashboard.html")
        get_template("geoflow_ops/gis/project_dashboard.html")


class DashboardScopeTests(TestCase):
    def test_map_and_counts_include_only_visible_enabled_projects(self):
        allowed=SimpleNamespace(id=uuid4(),ext={"gis_business_area":POINT},code="26001",name="Allowed")
        missing=SimpleNamespace(id=uuid4(),ext={},code="26002",name="Missing")
        forbidden=SimpleNamespace(id=uuid4(),ext={"gis_business_area":POINT},code="SECRET",name="Forbidden")
        class Query:
            def __init__(self, rows): self.rows=rows
            def filter(self, pk__in): return Query([p for p in self.rows if p.id in pk__in])
            def none(self): return Query([])
            def __iter__(self): return iter(self.rows)
        with patch.object(views,"_require_gis_view",return_value="tenant-a"),patch.object(views,"project_access_policy") as policy,patch.object(views,"_project_queryset",return_value=Query([allowed,missing,forbidden])),patch.object(views,"gis_enabled_project_ids",return_value=[allowed.id,missing.id,forbidden.id]),patch.object(views,"allowed_standard_names_for_projects",return_value=set()),patch.object(views,"_physical_feature_rows",return_value=[]),patch.object(views,"map_config",return_value={}),patch.object(views,"reverse",return_value="/allowed/"),patch.object(views,"render") as render:
            policy.return_value.visible_project_ids.return_value=[allowed.id,missing.id]
            views.dashboard(request(method="get"))
            context=render.call_args.args[2]
            self.assertEqual(context["projects"],[allowed,missing])
            self.assertEqual(context["located_project_count"],1)
            self.assertEqual(context["unlocated_project_count"],1)
            self.assertEqual([p["properties"]["code"] for p in context["map_projects"]],["26001"])
