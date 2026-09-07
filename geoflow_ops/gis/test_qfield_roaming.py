from django.test import SimpleTestCase

from .qfield_roaming import (
    DEFAULT_CELL_SIZE_M,
    cell_bbox,
    cell_key,
    parse_cell_key,
    plan_roaming_cells,
)


class QFieldRoamingPlannerTests(SimpleTestCase):
    def test_cell_key_roundtrip_and_bbox_are_stable(self):
        key = cell_key(DEFAULT_CELL_SIZE_M, 14123, 53001)
        size, ix, iy = parse_cell_key(key)
        self.assertEqual((size, ix, iy), (DEFAULT_CELL_SIZE_M, 14123, 53001))
        minx, miny, maxx, maxy = cell_bbox(size, ix, iy)
        self.assertLess(minx, maxx)
        self.assertLess(miny, maxy)
        self.assertGreaterEqual(minx, -180)
        self.assertLessEqual(maxx, 180)
        self.assertGreaterEqual(miny, -90)
        self.assertLessEqual(maxy, 90)

    def test_gps_plan_prioritizes_active_then_prefetch(self):
        plan = plan_roaming_cells(
            longitude=127.12,
            latitude=36.81,
            cell_size_m=250,
            active_radius_m=300,
            prefetch_radius_m=750,
            max_cells=192,
        )
        priorities = [cell.priority for cell in plan["cells"]]
        self.assertTrue(priorities)
        self.assertIn("active", priorities)
        self.assertIn("prefetch", priorities)
        first_prefetch = priorities.index("prefetch")
        self.assertTrue(all(value == "active" for value in priorities[:first_prefetch]))

    def test_viewport_cells_are_added_without_manual_aoi(self):
        plan = plan_roaming_cells(
            viewport_bbox=(127.10, 36.80, 127.11, 36.81),
            cell_size_m=250,
            max_cells=192,
        )
        self.assertGreater(plan["returned"], 0)
        self.assertTrue(all(cell.priority == "viewport" for cell in plan["cells"]))

    def test_known_cells_are_not_returned_again(self):
        first = plan_roaming_cells(
            longitude=127.12,
            latitude=36.81,
            cell_size_m=250,
            active_radius_m=300,
            prefetch_radius_m=750,
            max_cells=192,
        )
        known = {cell.key for cell in first["cells"][:5]}
        second = plan_roaming_cells(
            longitude=127.12,
            latitude=36.81,
            cell_size_m=250,
            active_radius_m=300,
            prefetch_radius_m=750,
            known_cells=known,
            max_cells=192,
        )
        self.assertTrue(known.isdisjoint({cell.key for cell in second["cells"]}))
        self.assertEqual(second["known_count"], len(known))

    def test_plan_is_bounded_for_large_viewport(self):
        plan = plan_roaming_cells(
            viewport_bbox=(126.8, 36.5, 127.5, 37.0),
            cell_size_m=250,
            max_cells=32,
        )
        self.assertEqual(plan["returned"], 32)
        self.assertTrue(plan["truncated"])

    def test_prefetch_radius_must_cover_active_radius(self):
        with self.assertRaises(ValueError):
            plan_roaming_cells(
                longitude=127.12,
                latitude=36.81,
                active_radius_m=800,
                prefetch_radius_m=300,
            )
