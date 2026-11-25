"""No infrastructure required. Run separately from full project settings."""

import io
import json
import stat
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="isolated-reference-tests-only",
        DEFAULT_CHARSET="utf-8",
        ALLOWED_HOSTS=["testserver"],
        ROOT_URLCONF=__name__,
        DATABASES={"default": {"ENGINE": "django.db.backends.dummy"}},
        INSTALLED_APPS=[],
        USE_I18N=False,
        TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates"}],
        MIDDLEWARE=["django.middleware.csrf.CsrfViewMiddleware"],
    )
    import django

    django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory
from django.urls import path

from control import views_gis_references as views
from control.services import gis_reference_files as files
from control.services import gis_references as refs

urlpatterns = [
    path("catalog/", views.catalog_api),
    path("upload/<uuid:dataset_id>/", views.upload_original),
    path("key/", views.vworld_key),
    path("lookup/", views.lookup_api),
]


def archive(members):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        for name, value in members:
            z.writestr(name, value)
    return stream.getvalue()


class ReferenceValidationTests(unittest.TestCase):
    def test_url_never_accepts_inline_keys_or_private_locations(self):
        for value in (
            "http://data.go.kr",
            "https://data.go.kr/?key=secret",
            "https://user:pass@data.go.kr/",
            "https://localhost/",
            "https://127.0.0.1/",
            "https://10.0.0.1/",
            "https://[::1]/",
        ):
            with self.subTest(value=value), self.assertRaises(refs.ReferenceError):
                refs.source_url(value)
        self.assertEqual(
            refs.source_url("https://www.data.go.kr/data/"),
            "https://www.data.go.kr/data/",
        )

    def test_secret_reference_is_not_a_raw_key_or_tenant_secret(self):
        for value in ("raw-api-secret", "aws-secretsmanager:geoflow/tenant/password"):
            with self.assertRaises(refs.ReferenceError):
                refs.secret_reference(value)
        self.assertTrue(
            refs.secret_reference(
                "aws-secretsmanager:geoflow/gis/references/vworld#api_key"
            )
        )

    def test_invalid_input_and_stale_revision_are_rejected(self):
        cur = MagicMock()
        for payload in (
            [],
            {"action": "delete"},
            {"action": "save_dataset", "kind": "unregistered"},
            {"action": "save_dataset", "kind": []},
        ):
            with self.assertRaises(refs.ReferenceError):
                refs.mutate(cur, payload, uuid4())
        cur.fetchone.return_value = (2,)
        with self.assertRaises(refs.ReferenceError):
            refs.mutate(
                cur,
                {
                    "action": "save_dataset",
                    "kind": "map_sheet",
                    "id": str(uuid4()),
                    "revision": 1,
                },
                uuid4(),
            )

    def test_catalogue_excludes_credential_and_object_keys(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        cur.fetchone.return_value = (0,)
        refs.snapshot(cur)
        source_sql = cur.execute.call_args_list[0].args[0]
        self.assertIn("credential_configured", source_sql)
        self.assertNotIn("SELECT *", source_sql)
        self.assertNotIn(
            "object_key", " ".join(c.args[0] for c in cur.execute.call_args_list)
        )

    def test_finalized_versions_cannot_be_overwritten(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(refs.ReferenceError):
            refs.finish_version(cur, uuid4(), uuid4(), True)
        self.assertIn("status='pending'", cur.execute.call_args.args[0])


class OriginalIntakeTests(unittest.TestCase):
    def inspect(self, name, value):
        stream, info = files.prepare(SimpleUploadedFile(name, value))
        self.addCleanup(stream.close)
        return stream, info

    def test_zip_shapefile_requires_no_user_extraction(self):
        value = archive(
            [(f"layer.{s}", b"sample") for s in ("shp", "shx", "dbf", "prj")]
        )
        stream, info = self.inspect("map.zip", value)
        self.assertEqual(stream.read(), value)
        self.assertEqual(info["size"], len(value))
        self.assertEqual(len(info["sha256"]), 64)

    def test_unsafe_members_executables_and_nested_archives_are_rejected(self):
        for name in ("../out.csv", "/out.csv", "a\\out.csv", "run.exe", "nested.zip"):
            with self.subTest(name=name), self.assertRaises(refs.ReferenceError):
                self.inspect("map.zip", archive([(name, b"x")]))

    def test_missing_shapefile_components_and_duplicate_paths_are_rejected(self):
        for members in ([("map.shp", b"x")], [("map.csv", b"x"), ("MAP.csv", b"y")]):
            with self.assertRaises(refs.ReferenceError):
                self.inspect("map.zip", archive(members))

    def test_symlink_is_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            entry = zipfile.ZipInfo("link.csv")
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(entry, "/etc/passwd")
        with self.assertRaises(refs.ReferenceError):
            self.inspect("map.zip", stream.getvalue())

    def test_empty_large_corrupt_and_high_ratio_files_are_rejected(self):
        for name, value in [
            ("map.zip", b"not-a-zip"),
            ("map.csv", b""),
            ("map.exe", b"x"),
        ]:
            with self.assertRaises(refs.ReferenceError):
                self.inspect(name, value)
        with (
            patch.object(files, "MAX_BYTES", 2),
            self.assertRaises(refs.ReferenceError),
        ):
            self.inspect("map.csv", b"abc")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("large.csv", b"0" * 100000)
        with self.assertRaises(refs.ReferenceError):
            self.inspect("map.zip", stream.getvalue())

    def test_storage_requires_bucket_and_uses_existing_private_storage(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            self.assertRaises(refs.ReferenceError),
        ):
            files.store(io.BytesIO(b"x"), "key")
        with (
            patch.dict(
                "os.environ",
                {
                    "AWS_S3_BUCKET": "isolated-test-bucket",
                    "GEOFLOW_CENTRAL_REFERENCE_UPLOAD_ENABLED": "true",
                },
            ),
            patch("geoflow_ops.services.s3_service.get_s3_client") as client,
            patch(
                "geoflow_ops.services.s3_service.get_bucket_name",
                return_value="isolated-test-bucket",
            ),
            patch(
                "geoflow_ops.services.s3_service.get_sse_config",
                return_value={"ServerSideEncryption": "AES256"},
            ),
        ):
            files.store(io.BytesIO(b"x"), "central/gis/references/test/original.zip")
            options = client.return_value.upload_fileobj.call_args.kwargs["ExtraArgs"]
            self.assertEqual(options["ServerSideEncryption"], "AES256")
            self.assertNotIn("ACL", options)
        with patch.dict(
            "os.environ",
            {
                "AWS_S3_BUCKET": "isolated-test-bucket",
                "GEOFLOW_CENTRAL_REFERENCE_UPLOAD_ENABLED": "false",
            },
            clear=True,
        ):
            self.assertFalse(files.uploads_enabled())

    def test_download_is_short_lived_attachment(self):
        with patch(
            "geoflow_ops.services.s3_service.generate_presigned_get_url",
            return_value="signed",
        ) as sign:
            self.assertEqual(files.download_url("key", "자료.zip"), "signed")
            self.assertEqual(sign.call_args.kwargs["expires_in"], 60)
            self.assertEqual(sign.call_args.kwargs["disposition"], "attachment")


class CentralRouteTests(unittest.TestCase):
    def authorized(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            patch(
                "control.decorators.lookup_user_id_from_request",
                return_value=str(uuid4()),
            )
        )
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            True,
        )
        stack.enter_context(
            patch("control.decorators.connections", {"default": connection})
        )
        return stack

    def test_all_routes_deny_anonymous_and_nonstaff_before_storage(self):
        for user in (None, str(uuid4())):
            with (
                patch(
                    "control.decorators.lookup_user_id_from_request", return_value=user
                ),
                patch("control.decorators.connections") as connections,
                patch.object(files, "store") as store,
            ):
                connections.__getitem__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = (
                    False,
                )
                for view, args, method in (
                    (views.dashboard, [], "get"),
                    (views.catalog_api, [], "get"),
                    (views.upload_original, [uuid4()], "post"),
                    (views.download_original, [uuid4()], "get"),
                ):
                    self.assertEqual(
                        view(getattr(RequestFactory(), method)("/"), *args).status_code,
                        403,
                    )
                store.assert_not_called()

    def test_csrf_is_enforced_for_mutations(self):
        self.authorized()
        for url in ("/catalog/", f"/upload/{uuid4()}/", "/key/", "/lookup/"):
            response = Client(enforce_csrf_checks=True).post(
                url, data="{}", content_type="application/json"
            )
            self.assertEqual(response.status_code, 403)

    def test_upload_success_and_failure_finalize_only_reserved_version(self):
        self.authorized()
        actor, version_id, dataset_id = (str(uuid4()) for _ in range(3))
        for success in (True, False):
            upload = SimpleUploadedFile("reference.csv", b"id,name\n1,point\n")
            request = RequestFactory().post("/", {"file": upload, "label": "v1"})
            request._dont_enforce_csrf_checks = True
            with (
                patch.object(files, "uploads_enabled", return_value=True),
                patch.object(
                    files,
                    "store",
                    side_effect=None
                    if success
                    else files.ReferenceStorageError("storage unavailable"),
                ),
                patch.object(views, "lookup_user_id_from_request", return_value=actor),
                patch.object(views, "connections", {"default": MagicMock()}),
                patch.object(views.transaction, "atomic"),
                patch.object(refs, "ready", return_value=True),
                patch.object(
                    refs, "reserve_version", return_value=(version_id, "reserved-key")
                ),
                patch.object(refs, "finish_version") as finish,
            ):
                response = views.upload_original(request, dataset_id)
                self.assertEqual(response.status_code, 201 if success else 503)
                self.assertEqual(
                    finish.call_args.args[1:], (actor, version_id, success)
                )
                self.assertEqual(json.loads(response.content)["ok"], success)

    def test_upload_gate_never_attempts_storage(self):
        self.authorized()
        request = RequestFactory().post("/")
        request._dont_enforce_csrf_checks = True
        with (
            patch.object(files, "uploads_enabled", return_value=False),
            patch.object(files, "store") as store,
        ):
            self.assertEqual(views.upload_original(request, uuid4()).status_code, 503)
            store.assert_not_called()

    def test_missing_schema_and_database_error_do_not_expose_sql(self):
        self.authorized()
        with (
            patch.object(views, "connections", {"default": MagicMock()}),
            patch.object(views.transaction, "atomic"),
            patch.object(refs, "ready", return_value=False),
        ):
            response = views.catalog_api(RequestFactory().get("/"))
            self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret_ref", response.content.decode())
        with (
            patch.object(views, "connections", {"default": MagicMock()}),
            patch.object(views.transaction, "atomic"),
            patch.object(
                refs, "ready", side_effect=views.DatabaseError("private sql parameters")
            ),
        ):
            response = views.catalog_api(RequestFactory().get("/"))
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private sql parameters", response.content.decode())

    def test_only_central_routes_exist_and_template_has_three_workspaces(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "control/templates/control/gis/references.html").read_text()
        for value in (
            'data-pane="datasets"',
            'data-pane="sources"',
            'data-pane="history"',
            "ref-query-form",
        ):
            self.assertIn(value, template)
        source = (root / "control/views_gis_references.py").read_text()
        self.assertNotIn("tenant_cursor", source)
        self.assertNotIn("requests.get", source)


if __name__ == "__main__":
    unittest.main()
