"""Pure policy tests for the shared Dynamic Form shape switch."""
from pathlib import Path
import sys
import unittest


PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR.parent))

from geoflow_connector.ui.behaviors.shape_switch import (  # noqa: E402
    FAMILIES,
    ShapeSwitchController,
)


class _Form:
    def __init__(self, values):
        self._values = dict(values)

    def values(self):
        return dict(self._values)


def _controller(family_index, values, shape="round", cleanup=True):
    config = FAMILIES[family_index]
    controller = object.__new__(ShapeSwitchController)
    controller.config = config
    controller._enabled = True
    controller._field_ids_by_key = {key: key for key in config.required_keys}
    controller._shape = shape
    controller._cleanup_allowed = cleanup
    controller.form = _Form(values)
    controller._log = lambda _message: None
    return controller


class ShapeSwitchPolicyTests(unittest.TestCase):
    def test_existing_sbc_values_select_round_or_rect(self):
        round_controller = _controller(0, {"sbc_size": 900})
        rect_controller = _controller(0, {"sbc_size_h": 800, "sbc_size_v": 600})

        self.assertEqual(round_controller._infer_shape(round_controller.form.values()),
                         ("round", False))
        self.assertEqual(rect_controller._infer_shape(rect_controller.form.values()),
                         ("rect", False))

    def test_repeated_switch_does_not_mutate_widget_drafts(self):
        drafts = {"sbc_size": 900, "sbc_size_h": 800, "sbc_size_v": 600}
        controller = _controller(0, drafts, shape="rect")

        rect_save = controller.prepare_save(dict(drafts))
        self.assertIsNone(rect_save["sbc_size"])
        self.assertEqual(controller.form.values(), drafts)

        controller._shape = "round"
        round_save = controller.prepare_save(dict(drafts))
        self.assertEqual(round_save["sbc_size"], 900)
        self.assertIsNone(round_save["sbc_size_h"])
        self.assertIsNone(round_save["sbc_size_v"])
        self.assertEqual(controller.form.values(), drafts)

    def test_dpg_depth_is_never_cleaned(self):
        drafts = {
            "dpg_std": 700,
            "dpg_std_h": 500,
            "dpg_std_v": 400,
            "dpg_dep": 1200,
        }
        controller = _controller(1, drafts, shape="round")
        round_save = controller.prepare_save(dict(drafts))
        self.assertEqual(round_save["dpg_dep"], 1200)
        self.assertIsNone(round_save["dpg_std_h"])
        self.assertIsNone(round_save["dpg_std_v"])

        controller._shape = "rect"
        rect_save = controller.prepare_save(dict(drafts))
        self.assertEqual(rect_save["dpg_dep"], 1200)
        self.assertIsNone(rect_save["dpg_std"])

    def test_conflict_preserves_both_sides_until_explicit_choice(self):
        drafts = {"sbc_size": 900, "sbc_size_h": 800, "sbc_size_v": 600}
        controller = _controller(0, drafts, cleanup=False)

        self.assertEqual(controller._infer_shape(drafts), ("round", True))
        self.assertEqual(controller.save_null_field_ids(), set())
        self.assertEqual(controller.prepare_save(dict(drafts)), drafts)

        controller._cleanup_allowed = True
        self.assertEqual(
            controller.save_null_field_ids(), {"sbc_size_h", "sbc_size_v"}
        )

    def test_empty_values_default_to_round(self):
        controller = _controller(0, {})
        self.assertEqual(controller._infer_shape({}), ("round", False))


if __name__ == "__main__":
    unittest.main()
