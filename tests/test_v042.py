import importlib
import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import patch

import numpy as np

import isp_tool
from isp_tool.models import RawMetadata, StageResult
from isp_tool.ui.performance_metrics import PerformanceMetrics
from isp_tool.ui.render_cache import RenderCache
from isp_tool.ui.scrolling import normalize_wheel_delta
from isp_tool.ui.theme import FONTS, configure_theme
from isp_tool.ui.widgets import ActionMenu


class RenderCacheTests(unittest.TestCase):
    def test_stage_cache_is_bounded_and_revision_is_part_of_key(self):
        cache = RenderCache(stage_capacity=2, analysis_capacity=2)
        first = cache.stage_key(1, 0, "bayer", 3)
        second = cache.stage_key(1, 1, "rgb", 3)
        next_revision = cache.stage_key(2, 0, "bayer", 3)
        cache.put_stage(first, "first")
        cache.put_stage(second, "second")
        self.assertEqual(cache.get_stage(first), "first")
        cache.put_stage(next_revision, "new")
        self.assertIsNone(cache.get_stage(second))
        self.assertEqual(cache.get_stage(next_revision), "new")

    def test_analysis_key_tracks_roi_and_settings(self):
        cache = RenderCache()
        key_a = cache.analysis_key(
            4, 2, "Waveform", (0, 0, 20, 20), "RGB Overlay", 384, 105
        )
        key_b = cache.analysis_key(
            4, 2, "Waveform", (2, 0, 20, 20), "RGB Overlay", 384, 105
        )
        key_c = cache.analysis_key(
            4, 2, "Waveform", (0, 0, 20, 20), "Luma", 384, 105
        )
        self.assertNotEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_c)

    def test_clear_analysis_preserves_stage_rgb(self):
        cache = RenderCache()
        stage = cache.stage_key(1, 0, "rgb", 1)
        analysis = cache.analysis_key(1, 0, "Histogram", None)
        cache.put_stage(stage, np.zeros((2, 2, 3), np.float32))
        cache.put_analysis(analysis, {"Y": np.zeros(256)})
        cache.clear_analysis()
        self.assertIsNotNone(cache.get_stage(stage))
        self.assertIsNone(cache.get_analysis(analysis))


class PerformanceAndInputTests(unittest.TestCase):
    def test_rolling_metrics_report_p50_and_p95(self):
        metrics = PerformanceMetrics(window=4)
        for value in (1, 2, 3, 100, 5):
            metrics.record("view", value)
        summary = metrics.summary("view")
        self.assertEqual(summary["count"], 4)
        self.assertEqual(summary["latest"], 5.0)
        self.assertGreaterEqual(summary["p95"], summary["p50"])
        self.assertIn("p50", metrics.details_text())

    def test_wheel_normalization_supports_windows_and_x11(self):
        self.assertEqual(normalize_wheel_delta(120), -1.0)
        self.assertEqual(normalize_wheel_delta(-120), 1.0)
        self.assertEqual(normalize_wheel_delta(button_number=4), -1.0)
        self.assertEqual(normalize_wheel_delta(button_number=5), 1.0)

    def test_dpi_helper_is_safe_and_idempotent_off_windows(self):
        from isp_tool.ui import dpi

        module = importlib.reload(dpi)
        self.assertEqual(
            module.enable_process_dpi_awareness("linux"), "not-windows"
        )
        self.assertEqual(
            module.enable_process_dpi_awareness("win32"), "not-windows"
        )


class DeferredAnalysisTests(unittest.TestCase):
    def test_worker_computes_only_requested_analysis_type(self):
        from isp_tool.ui.app import ISPApplication

        image = np.zeros((8, 8, 3), np.float32)
        metadata = RawMetadata(width=8, height=8)
        histogram = {
            key: np.zeros(256, np.int64) for key in ("R", "G", "B", "Y")
        }
        with patch(
            "isp_tool.ui.app.compute_histogram", return_value=histogram
        ) as hist, patch(
            "isp_tool.ui.app.compute_waveform"
        ) as waveform, patch(
            "isp_tool.ui.app.compute_vectorscope"
        ) as vectorscope, patch(
            "isp_tool.ui.app.compute_statistics"
        ) as statistics:
            payload = ISPApplication._compute_analysis_payload(
                "Histogram", image, "rgb", metadata, "", 1.0, 0, 0
            )
        hist.assert_called_once()
        waveform.assert_not_called()
        vectorscope.assert_not_called()
        statistics.assert_not_called()
        self.assertIs(payload["value"], histogram)


class HiddenTkV042Tests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    def test_fast_view_does_not_schedule_analysis_unless_requested(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            app.generation += 1
            app.results = [
                StageResult(
                    "input",
                    "Input",
                    np.full((8, 8, 3), 0.25, np.float32),
                    "rgb",
                    0.0,
                )
            ]
            app.result_revision += 1
            app.stage_combo.current(0)
            with patch.object(app, "schedule_analysis_refresh") as schedule:
                app.render_current()
                schedule.assert_not_called()
                app.render_current(schedule_analysis=True)
                schedule.assert_called_once()
            app.render_cache.clear()
            with patch(
                "isp_tool.ui.app.display_rgb",
                wraps=__import__(
                    "isp_tool.ui.app", fromlist=["display_rgb"]
                ).display_rgb,
            ) as convert:
                app._stage_rgb(0)
                app._stage_rgb(0)
                convert.assert_called_once()
            tabs = [
                app.analysis_notebook.tab(tab, "text")
                for tab in app.analysis_notebook.tabs()
            ]
            self.assertEqual(
                tabs,
                ["Histogram", "Waveform", "Vectorscope", "Statistics"],
            )
            app._on_canvas_resize()
            first_resize = app.canvas_resize_after
            app._on_canvas_resize()
            second_resize = app.canvas_resize_after
            self.assertNotEqual(first_resize, second_resize)
            self.assertNotIn(
                first_resize, root.tk.call("after", "info")
            )
            self.assertNotIn(str(app.image_canvas), app.wheel_router._targets)
            app.analysis_collapsed = True
            with patch.object(app, "_start_analysis") as start:
                app.schedule_analysis_refresh(0)
                root.update()
                start.assert_not_called()
            app.analysis_collapsed = False
            app.analysis_generation = 5
            payload = {
                "value": {
                    key: np.zeros(256, np.int64)
                    for key in ("R", "G", "B", "Y")
                },
                "elapsed_ms": 1.0,
            }
            with patch.object(app, "_render_histogram") as render:
                app._apply_analysis_payload(
                    4, ("stale",), "Histogram", 0, payload
                )
                render.assert_not_called()
        finally:
            if root.winfo_exists():
                app.close()

    def test_action_menu_dynamic_state_and_named_font_scaling(self):
        root = self._root()
        try:
            enabled = tk.BooleanVar(root, value=False)
            menu = ActionMenu(root, "Actions")
            called = []
            index = menu.add_command(
                "Run", lambda: called.append(True),
                enabled=enabled.get,
            )
            menu.refresh_states()
            self.assertEqual(str(menu.menu.entrycget(index, "state")), "disabled")
            enabled.set(True)
            menu.refresh_states()
            self.assertEqual(str(menu.menu.entrycget(index, "state")), "normal")
            menu.menu.invoke(index)
            self.assertEqual(called, [True])

            configure_theme(root, 1.0)
            normal = int(
                tkfont.Font(
                    root=root, name=FONTS["body"], exists=True
                ).cget("size")
            )
            configure_theme(root, 1.25)
            enlarged = int(
                tkfont.Font(
                    root=root, name=FONTS["body"], exists=True
                ).cget("size")
            )
            self.assertGreaterEqual(normal, 10)
            self.assertGreater(enlarged, normal)
            root.update()
        finally:
            root.destroy()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v042(self):
        version = tuple(
            int(part) for part in isp_tool.__version__.split(".")
        )
        self.assertGreaterEqual(version, (0, 4, 2))


if __name__ == "__main__":
    unittest.main()
