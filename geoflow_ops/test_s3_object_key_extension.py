from django.test import SimpleTestCase

from geoflow_ops.services.s3_service import extract_extension


class S3ObjectKeyExtensionTests(SimpleTestCase):
    def test_normal_document_extensions_are_preserved(self):
        self.assertEqual(extract_extension("report.PDF"), "pdf")
        self.assertEqual(extract_extension("drawing.dwg"), "dwg")
        self.assertEqual(extract_extension("archive.tar.gz"), "gz")

    def test_unsafe_or_structural_extensions_fall_back_to_bin(self):
        for filename in (
            "no-extension",
            "file.",
            "file.txt/child",
            "file.../../html",
            "file.a-b",
            "file.%2fhtml",
            "file.abcdefghijklmnopq",
        ):
            with self.subTest(filename=filename):
                self.assertEqual(extract_extension(filename), "bin")
