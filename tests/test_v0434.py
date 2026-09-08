import tkinter as tk
import time
import unittest

import numpy as np

from isp_tool import __version__
from isp_tool.i18n import Translator
from isp_tool.ui.app import ISPApplication
from isp_tool.ui.performance_metrics import (
    PerformanceMetrics,
    estimate_ndarray_bytes,
    format_bytes,
)
from isp_tool.ui.performance_monitor import PerformanceMonitorWindow


class PerformanceMetricsV0434Tests(unittest.TestCase):
    def test_timing_summary_includes_latest_average_p95_and_max(self):
        metrics = PerformanceMetrics(window=4)
        for value in (2, 4, 8, 16, 32):
            metrics.record("pipeline", value)
        summary = metrics.summary("pipeline")
        self.assertEqual(summary["latest"], 32.0)
        self.assertEqual(summary["maximum"], 32.0)
        self.assertEqual(summary["count"], 4)
        self.assertGreaterEqual(summary["p95"], summary["average"])

    def test_cache_rate_is_cumulative_and_zero_safe(self):
        metrics = PerformanceMetrics()
        self.assertEqual(metrics.cache_summary("pipeline").hit_rate, 0.0)
        metrics.add_cache("pipeline", hits=3, misses=1)
        metrics.add_cache("pipeline", hits=2, misses=4)
        cache = metrics.cache_summary("pipeline")
        self.assertEqual((cache.hits, cache.misses), (5, 5))
        self.assertEqual(cache.hit_rate, 0.5)

    def test_array_memory_estimate_deduplicates_views(self):
        base = np.zeros((10, 10), dtype=np.float32)
        view = base[:, :5]
        independent = base.copy()
        self.assertEqual(
            estimate_ndarray_bytes(base, view, {"copy": independent}),
            base.nbytes + independent.nbytes,
        )
        self.assertEqual(format_bytes(1024 * 1024), "1.0 MiB")

    def test_status_identifies_slowest_module_cache_and_memory(self):
        metrics = PerformanceMetrics()
        metrics.record("pipeline", 24)
        metrics.record("module:WB", 3)
        metrics.record("module:Demosaic", 11)
        metrics.set_cache("pipeline", 8, 2)
        metrics.set_memory("estimated_runtime", 2 * 1024 * 1024)
        status = metrics.status_text()
        self.assertIn("Demosaic 11 ms", status)
        self.assertIn("Cache 80%", status)
        self.assertIn("Memory ~2.0 MiB", status)

    def test_snapshot_keeps_structured_cache_memory_and_task_data(self):
        metrics = PerformanceMetrics()
        metrics.set_cache("display", 4, 1)
        metrics.set_memory("estimated_runtime", 2048)
        metrics.increment("preview_results_stale", 2)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["caches"]["display"]["requests"], 5)
        self.assertEqual(snapshot["memory_bytes"]["estimated_runtime"], 2048)
        self.assertEqual(snapshot["counters"]["preview_results_stale"], 2)


class HiddenTkPerformanceMonitorTests(unittest.TestCase):
    def test_monitor_is_non_modal_and_uses_three_compact_tabs(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        metrics = PerformanceMetrics()
        metrics.record("pipeline", 7)
        metrics.set_cache("pipeline", 1, 1)
        metrics.set_memory("estimated_runtime", 1024)
        translator = Translator("zh_CN")
        window = PerformanceMonitorWindow(root, metrics, translator.tr)
        try:
            root.update_idletasks()
            self.assertEqual(len(window.notebook.tabs()), 3)
            self.assertTrue(window.timing_tree.get_children())
            self.assertTrue(window.cache_tree.get_children())
            self.assertTrue(window.memory_tree.get_children())
            self.assertEqual(window.transient(), "")
        finally:
            if window.winfo_exists():
                window.close()
            if root.winfo_exists():
                root.destroy()

    def test_app_records_preview_lifecycle_and_opens_monitor(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        app = ISPApplication(root)
        try:
            deadline = time.time() + 6.0
            while time.time() < deadline:
                root.update()
                counters = app.performance.snapshot()["counters"]
                if counters.get("preview_tasks_completed", 0):
                    break
                time.sleep(0.01)
            counters = app.performance.snapshot()["counters"]
            self.assertGreaterEqual(counters["preview_tasks_submitted"], 1)
            self.assertGreaterEqual(counters["preview_tasks_completed"], 1)
            self.assertTrue(app.performance_status_label.winfo_manager())
            app.show_performance_details()
            root.update_idletasks()
            self.assertEqual(len(app.performance_window.notebook.tabs()), 3)
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_v0434(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 34)
        )


if __name__ == "__main__":
    unittest.main()
