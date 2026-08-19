import os
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from isp_tool import __version__
from isp_tool.i18n import Translator, load_language, save_language
from isp_tool.models import ImageROI
from isp_tool.ui.app import ISPApplication


class TranslationModelTests(unittest.TestCase):
    def test_resources_fallback_and_formatting(self):
        zh = Translator("zh_CN")
        en = Translator("en_US")
        self.assertEqual(zh.tr("menu.file"), "文件")
        self.assertEqual(en.tr("menu.file"), "File")
        self.assertEqual(
            en.tr("i18n.fallback_probe"), "默认语言回退"
        )
        self.assertEqual(
            en.tr("toolbar.preview_ev", ev=1.5), "Preview +1.5 EV"
        )
        self.assertEqual(en.tr("missing.translation.key"), "missing.translation.key")

    def test_professional_terms_remain_readable(self):
        for language in ("zh_CN", "en_US"):
            translator = Translator(language)
            joined = " ".join(
                translator.tr(key)
                for key in (
                    "menu.open", "toolbar.auto", "toolbar.histogram",
                    "toolbar.export_roi",
                )
            )
            for term in ("RAW", "YUV", "Histogram", "ROI"):
                self.assertIn(term, joined)

    def test_language_preference_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ui_preferences.json"
            self.assertTrue(save_language("en_US", path))
            self.assertEqual(load_language(path), "en_US")
            self.assertTrue(save_language("invalid", path))
            self.assertEqual(load_language(path), "zh_CN")


class HiddenTkLanguageTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.tempdir = tempfile.TemporaryDirectory()
        self.preference_path = str(
            Path(self.tempdir.name) / "ui_preferences.json"
        )
        self.environment = patch.dict(
            os.environ,
            {"ISP_TOOL_PREFERENCES_PATH": self.preference_path},
        )
        self.environment.start()
        self.app = ISPApplication(self.root)
        deadline = time.time() + 4.0
        while time.time() < deadline and not self.app.results:
            self.root.update()
            time.sleep(0.01)

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.close()
        self.environment.stop()
        self.tempdir.cleanup()

    def test_runtime_switch_preserves_workspace_and_does_not_process(self):
        self.app.rois = [ImageROI(2, 2, 12, 10)]
        self.app.roi = self.app.rois[0]
        self.app.active_roi_index = 0
        module = self.app.pipeline.module_by_id("white_balance")
        module.parameters["r_gain"] = 1.75
        snapshot = self.app.pipeline.snapshot()
        loaded = self.app.loaded
        results = self.app.results
        generation = self.app.generation
        pending_after = self.app.pending_after
        process_requests = []
        original_schedule = self.app.schedule_process
        self.app.schedule_process = (
            lambda immediate=False: process_requests.append(immediate)
        )

        try:
            self.app.language_var.set("en_US")
            self.app._change_language()
        finally:
            self.app.schedule_process = original_schedule

        self.assertIs(self.app.loaded, loaded)
        self.assertIs(self.app.results, results)
        self.assertEqual(self.app.roi, ImageROI(2, 2, 12, 10))
        self.assertEqual(self.app.pipeline.snapshot(), snapshot)
        self.assertEqual(self.app.generation, generation)
        self.assertEqual(self.app.pending_after, pending_after)
        self.assertEqual(process_requests, [])
        self.assertEqual(self.app.import_image_button["text"], "Import Images")
        self.assertEqual(self.app.manual_mode_button["text"], "Manual")
        self.assertEqual(
            self.app.main_menu.entrycget("end", "label"),
            "Language / 语言",
        )
        self.assertEqual(load_language(Path(self.preference_path)), "en_US")

    def test_awb_is_compact_and_histogram_switches_language(self):
        panel = self.app.calibration_workspace.auto_panel
        panel.select_module("AWB")
        self.root.update_idletasks()
        self.assertEqual(panel.method_help_var.get(), "")
        self.assertEqual(panel.awb_roi_status_var.get(), "")
        self.assertEqual(panel.method_help_label.winfo_manager(), "")
        self.assertEqual(panel.awb_roi_status_label.winfo_manager(), "")

        self.app.open_histogram_window()
        histogram = self.app.histogram_window
        self.app.open_final_preview()
        final_preview = self.app.final_preview_window
        self.app.language_var.set("en_US")
        self.app._change_language()
        self.assertEqual(panel.method_label["text"], "AWB Method")
        self.assertEqual(panel.analyze_button["text"], "Calibrate and Apply")
        self.assertEqual(histogram.y_axis_label["text"], "Y Axis")
        self.assertEqual(histogram.title(), "Histogram")
        self.assertEqual(
            final_preview.title(), "Final Effect and Module Impact"
        )
        self.assertEqual(
            final_preview.refresh_button["text"],
            "Refresh Current Image and Parameters",
        )


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0425(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 25)
        )


if __name__ == "__main__":
    unittest.main()
