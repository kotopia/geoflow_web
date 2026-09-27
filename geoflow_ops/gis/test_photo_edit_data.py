"""DB-free validation tests for GIS photo annotation edit_data."""

import unittest

from .photo_edit_data import MAX_ANNOTATIONS, MAX_POINTS, validate_edit_data


def document(rows):
    return {"version": 2, "format": "annotation-json",
            "canvas": {"width": 1920, "height": 1080}, "annotations": rows}


class PhotoEditDataTests(unittest.TestCase):
    def test_all_annotation_types_and_style_are_accepted(self):
        rows = [
            {"id":"a1","type":"line","start":[1,2],"end":[3,4],"stroke":"#ff0000"},
            {"id":"a2","type":"polyline","points":[[1,2],[3,4]]},
            {"id":"a3","type":"freehand","points":[[1,2],[3,4]],"stroke_width":5},
            {"id":"a4","type":"rectangle","x":1,"y":2,"width":30,"height":40,"fill":"#44000000"},
            {"id":"a5","type":"ellipse","x":1,"y":2,"width":30,"height":40,"opacity":.5},
            {"id":"a6","type":"text","text":"관로 위치","x":1,"y":2,"font_size":28,"bold":True},
            {"id":"a7","type":"icon","icon":"warning","x":1,"y":2,"size":76,"rotation":30},
        ]
        self.assertEqual(validate_edit_data(document(rows))["annotations"], rows)

    def test_legacy_raster_documents_remain_readable(self):
        for value in ({"version":1,"format":"raster-png"},
                      {"version":2,"format":"raster-jpeg"}):
            self.assertEqual(validate_edit_data(value), value)

    def test_limits_unknown_types_and_duplicate_ids_are_rejected(self):
        invalid = [
            document([{"id":f"a{i}","type":"line","start":[0,0],"end":[1,1]}
                      for i in range(MAX_ANNOTATIONS + 1)]),
            document([{"id":"a","type":"freehand","points":[[0,0]]*(MAX_POINTS+1)}]),
            document([{"id":"a","type":"script"}]),
            document([{"id":"a","type":"line","start":[0,0],"end":[1,1]},
                      {"id":"a","type":"line","start":[0,0],"end":[1,1]}]),
            document([{"id":"a","type":"line","start":[float("nan"),0],"end":[1,1]}]),
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError): validate_edit_data(value)


if __name__ == "__main__":
    unittest.main()

