"""Runtime tests for bounded JPEG normalization and metadata preservation."""
import os
from pathlib import Path
import tempfile
import unittest

from PIL import ExifTags, Image

from .ui.photo_normalizer import MAX_PHOTO_BYTES, normalize_photo


class PhotoNormalizerTests(unittest.TestCase):
    def test_large_smartphone_jpegs_normalize_below_500kb(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = os.urandom(3000 * 2200 * 3)
            image = Image.frombytes("RGB", (3000, 2200), raw)
            for index, quality in enumerate((88, 94, 100)):
                path = Path(directory) / f"phone-{index}.jpg"
                exif = Image.Exif(); exif[0x0112] = 6; exif[0x010F] = "GeoFlow Test"
                exif[0x0110] = "Field Camera"; exif[0x9003] = "2026:09:27 14:00:00"
                image.save(path, "JPEG", quality=quality, exif=exif)
                self.assertGreater(path.stat().st_size, 2 * 1024 * 1024)
                result = normalize_photo(path)
                self.assertLessEqual(len(result.data), MAX_PHOTO_BYTES)
                self.assertEqual(result.mime_type, "image/jpeg")
                self.assertEqual(result.image_metadata["source_orientation"], 6)
                self.assertEqual(result.image_metadata["normalization"]["rotation_applied"], 90)
                self.assertEqual(result.image_metadata["exif"]["Model"], "Field Camera")

    def test_image_without_exif_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plain.jpg"
            Image.new("RGB", (800, 600), "white").save(path, "JPEG")
            result = normalize_photo(path)
            self.assertLessEqual(len(result.data), MAX_PHOTO_BYTES)
            self.assertEqual(result.image_metadata["source_orientation"], 1)

    def test_camera_exif_sub_ifd_and_offset_time_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "camera.jpg"
            exif = Image.Exif()
            exif.get_ifd(ExifTags.IFD.Exif)[0x9003] = "2026:09:27 14:00:00"
            exif.get_ifd(ExifTags.IFD.Exif)[0x9011] = "+09:00"
            Image.new("RGB", (1200, 800), "blue").save(path, "JPEG", exif=exif)
            result = normalize_photo(path)
            self.assertEqual(result.image_metadata["exif"]["DateTimeOriginal"],
                             "2026:09:27 14:00:00")
            self.assertEqual(result.captured_at, "2026-09-27T14:00:00+09:00")


if __name__ == "__main__":
    unittest.main()
