import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from isp_tool import __version__
from isp_tool.i18n import Translator
from isp_tool.ui.controllers import (
    LanguageController,
    YUVPreviewController,
)
from isp_tool.validation import (
    build_pipeline_baseline,
    verify_pipeline_baseline,
)
from isp_tool.yuv import YUVMetadata


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = (
    PROJECT_ROOT / "examples" / "baselines" / "v0425_pipeline.json"
)


class LanguageControllerTests(unittest.TestCase):
    def test_language_state_is_owned_without_requiring_widgets(self):
        controller = LanguageController(translator=Translator("zh_CN"))
        self.assertTrue(controller.set_language("en_US", persist=False))
        self.assertEqual(controller.language, "en_US")
        self.assertIn("Import", controller.tr("toolbar.import"))
        self.assertFalse(controller.set_language("en_US", persist=False))

    def test_language_can_restore_from_ui_state(self):
        controller = LanguageController(translator=Translator("zh_CN"))
        self.assertTrue(controller.restore_from_ui_state(
            {"language": "en_US"}, persist=False
        ))
        self.assertEqual(controller.language, "en_US")
        self.assertFalse(controller.restore_from_ui_state({}, persist=False))


class YUVPreviewControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "4x2_nv12.yuv"
        y = np.arange(8, dtype=np.uint8).reshape(2, 4) + 16
        u = np.array([[80, 90]], dtype=np.uint8)
        v = np.array([[160, 170]], dtype=np.uint8)
        uv = np.stack((u, v), axis=-1)
        self.path.write_bytes(y.tobytes() + uv.tobytes())
        self.metadata = YUVMetadata(4, 2, "NV12")
        self.controller = YUVPreviewController()

    def tearDown(self):
        self.temp.cleanup()

    def test_controller_builds_the_four_existing_preview_stages(self):
        payload = self.controller.process(
            str(self.path), self.metadata, 1500, lambda: False
        )
        self.assertEqual(
            [result.module_id for result in payload["results"]],
            [
                "yuv_input",
                "chroma_upsampling",
                "yuv_to_rgb",
                "display_preview",
            ],
        )
        self.assertEqual(payload["conversion"].rgb.shape, (2, 4, 3))
        self.assertTrue(np.all(np.isfinite(payload["conversion"].rgb)))
        self.assertEqual(payload["metrics"]["recomputed"], 3)

    def test_cache_key_tracks_conversion_metadata(self):
        first = self.controller.cache_key(
            str(self.path), self.metadata, 1500
        )
        changed = copy.deepcopy(self.metadata)
        changed.color_matrix = "BT.601"
        second = self.controller.cache_key(str(self.path), changed, 1500)
        self.assertNotEqual(first, second)

    def test_cancelled_request_stops_before_conversion(self):
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.controller.process(
                str(self.path), self.metadata, 1500, lambda: True
            )


class GoldenPipelineBaselineTests(unittest.TestCase):
    def test_committed_golden_pipeline_matches_current_algorithms(self):
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        fixture = expected["fixture"]
        actual = build_pipeline_baseline(
            width=fixture["width"],
            height=fixture["height"],
            patterns=fixture["patterns"],
        )
        self.assertEqual(verify_pipeline_baseline(expected, actual), [])

    def test_golden_verifier_identifies_the_changed_stage(self):
        actual = build_pipeline_baseline(
            width=64, height=64, patterns=("RGGB",)
        )
        expected = copy.deepcopy(actual)
        expected["cases"]["RGGB"]["stages"]["demosaic"][
            "quantized_sha256"
        ] = "0" * 64
        errors = verify_pipeline_baseline(expected, actual)
        self.assertIn(
            "RGGB/demosaic: quantized_sha256 differs", errors
        )

    def test_version_is_at_least_v0426(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 26)
        )


if __name__ == "__main__":
    unittest.main()
