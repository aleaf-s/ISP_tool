import copy
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from isp_tool import __version__
from isp_tool.models import CalibrationSession
from isp_tool.raw_io import synthetic_bayer
from isp_tool.ui.app import ISPApplication
from isp_tool.workspace import ImageWorkItem


class HiddenTkWorkspaceCacheTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    def _small_app(self):
        root = self._root()
        app = ISPApplication(root)
        root.update_idletasks()
        loaded = synthetic_bayer(320, 240)
        app.loaded = loaded
        app.work_items[0].loaded = loaded
        app.input_revision += 1
        app._prepare_preview()
        app.pipeline_cache = {}
        app.results = []
        app.schedule_process(immediate=True)
        self._wait_processed(root, app)
        return root, app

    @staticmethod
    def _wait_processed(root, app, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            root.update()
            item = app.work_items[app.current_image_index]
            if (
                app.results
                and item.runtime_preview is not None
                and (
                    app.current_future is None
                    or app.current_future.done()
                )
            ):
                return
            time.sleep(0.005)
        raise AssertionError("preview processing did not complete")

    @staticmethod
    def _append_second(app):
        loaded = synthetic_bayer(300, 200)
        app.work_items.append(
            ImageWorkItem(
                loaded,
                copy.deepcopy(app.pipeline.snapshot()),
                CalibrationSession(
                    raw_metadata=copy.deepcopy(loaded.metadata)
                ),
            )
        )

    def _close(self, root, app):
        if root.winfo_exists():
            root.update_idletasks()
            app.close()

    def test_switching_back_restores_results_without_submitting_pipeline(self):
        root, app = self._small_app()
        try:
            first_state = app.work_items[0].runtime_preview
            first_final = first_state.results[-1].image
            self._append_second(app)
            app._activate_work_item(1)
            self._wait_processed(root, app)

            generation = app.generation
            with patch.object(app, "schedule_process") as schedule:
                app._activate_work_item(0)
                schedule.assert_not_called()
            self.assertGreater(app.generation, generation)
            self.assertIn("多图缓存恢复", app.status_var.get())
            self.assertIs(app.results[-1].image, first_final)
            counters = app.performance.snapshot()["counters"]
            self.assertGreaterEqual(
                counters.get("workspace_cache_hits", 0), 1
            )
            self.assertIn(
                "images",
                app.performance.snapshot()["values"][
                    "workspace_preview_cache"
                ],
            )
        finally:
            self._close(root, app)

    def test_parameter_snapshot_change_invalidates_target_cache(self):
        root, app = self._small_app()
        try:
            self._append_second(app)
            app._activate_work_item(1)
            self._wait_processed(root, app)
            ccm = next(
                item
                for item in app.work_items[0].pipeline_snapshot
                if item["id"] == "color_correction_matrix"
            )
            ccm["parameters"]["strength"] = 0.8

            with patch.object(app, "schedule_process") as schedule:
                app._activate_work_item(0)
                schedule.assert_called_once_with(immediate=True)
            self.assertIsNone(app.work_items[0].runtime_preview)
            self.assertFalse(app.results)
            counters = app.performance.snapshot()["counters"]
            self.assertGreaterEqual(
                counters.get("workspace_cache_invalidations", 0),
                1,
            )
        finally:
            self._close(root, app)

    def test_lru_capacity_evicts_oldest_noncurrent_image(self):
        root, app = self._small_app()
        try:
            app.runtime_cache_max_items = 1
            self._append_second(app)
            app._activate_work_item(1)
            self._wait_processed(root, app)
            self.assertIsNone(app.work_items[0].runtime_preview)
            self.assertIsNotNone(app.work_items[1].runtime_preview)
            counters = app.performance.snapshot()["counters"]
            self.assertGreaterEqual(
                counters.get("workspace_cache_evictions", 0), 1
            )
        finally:
            self._close(root, app)

    def test_memory_budget_evicts_oldest_noncurrent_image(self):
        root, app = self._small_app()
        try:
            first_memory = (
                app.work_items[0].runtime_preview.memory_bytes
            )
            app.runtime_cache_max_items = 3
            app.runtime_cache_budget_bytes = first_memory + 1
            self._append_second(app)
            app._activate_work_item(1)
            self._wait_processed(root, app)
            self.assertIsNone(app.work_items[0].runtime_preview)
            self.assertIsNotNone(app.work_items[1].runtime_preview)
            total = sum(
                item.runtime_preview.memory_bytes
                for item in app.work_items
                if item.runtime_preview is not None
            )
            self.assertLessEqual(
                total, app.runtime_cache_budget_bytes
            )
        finally:
            self._close(root, app)

    def test_manual_clear_releases_all_runtime_entries(self):
        root, app = self._small_app()
        try:
            self._append_second(app)
            app._activate_work_item(1)
            self._wait_processed(root, app)
            app.clear_runtime_preview_cache()
            self.assertTrue(
                all(
                    item.runtime_preview is None
                    for item in app.work_items
                )
            )
            self.assertTrue(
                app.performance.snapshot()["values"][
                    "workspace_preview_cache"
                ].startswith("0/")
            )
        finally:
            self._close(root, app)


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v048(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 8)
        )


if __name__ == "__main__":
    unittest.main()
