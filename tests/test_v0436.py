from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import tkinter as tk
import unittest

from PIL import Image

from isp_tool import __version__
from isp_tool.ui.app import ISPApplication
from isp_tool.ui.controllers import (
    ACTION_APPLY,
    ACTION_CANCELLED,
    ACTION_STALE,
    ACTION_WAIT,
    ImportFailure,
    ImportPayloadError,
    ImportRequestCoordinator,
    ImportResultApplicationController,
)


class FakeScheduler:
    def __init__(self):
        self.callbacks = {}
        self.cancelled = []
        self.next_id = 0

    def after(self, delay_ms, callback):
        self.next_id += 1
        callback_id = f"after-{self.next_id}"
        self.callbacks[callback_id] = (int(delay_ms), callback)
        return callback_id

    def after_cancel(self, callback_id):
        self.cancelled.append(callback_id)
        self.callbacks.pop(callback_id, None)

    def run(self, callback_id):
        _delay, callback = self.callbacks.pop(callback_id)
        callback()


class RunningFuture:
    def __init__(self):
        self.cancel_calls = 0

    def done(self):
        return False

    def cancel(self):
        self.cancel_calls += 1
        return False


class ImportControllerTests(unittest.TestCase):
    def test_begin_supersedes_running_future_and_close_cleans_polls(self):
        scheduler = FakeScheduler()
        superseded = []
        coordinator = ImportRequestCoordinator(
            scheduler,
            on_request_superseded=lambda: superseded.append(1),
        )
        first = coordinator.begin()
        future = RunningFuture()
        coordinator.bind_future(future)
        second = coordinator.begin()
        self.assertGreater(second, first)
        self.assertEqual(future.cancel_calls, 1)
        self.assertEqual(superseded, [1])
        self.assertIsNone(coordinator.current_future)
        coordinator.schedule_poll(lambda: None)
        callback_id = next(iter(coordinator.poll_after_ids))
        coordinator.close()
        self.assertTrue(coordinator.closed)
        self.assertIn(callback_id, scheduler.cancelled)

    def test_result_decision_has_latest_generation_priority(self):
        controller = ImportResultApplicationController()
        self.assertEqual(
            controller.decide(is_current=False, done=False), ACTION_STALE
        )
        self.assertEqual(
            controller.decide(is_current=True, done=False), ACTION_WAIT
        )
        self.assertEqual(
            controller.decide(
                is_current=True, done=True, cancelled=True
            ),
            ACTION_CANCELLED,
        )
        self.assertEqual(
            controller.decide(is_current=True, done=True), ACTION_APPLY
        )

    def test_payload_contract_accepts_partial_success(self):
        controller = ImportResultApplicationController()
        item = SimpleNamespace(
            loaded=SimpleNamespace(source_path=Path("a.png")),
            pipeline_snapshot=[],
            calibration_session=object(),
        )
        paths = ("a.png", "b.png")
        prepared = controller.prepare(
            {
                "requested_paths": paths,
                "items": [item],
                "failures": [ImportFailure("b.png", "bad image")],
                "elapsed_ms": 3.5,
            },
            paths,
        )
        self.assertEqual((prepared.succeeded, prepared.failed), (1, 1))
        self.assertEqual(
            prepared.failure_messages, ("b.png: bad image",)
        )

    def test_payload_rejects_wrong_batch_and_incomplete_outcome(self):
        controller = ImportResultApplicationController()
        base = {
            "requested_paths": ("old.png",),
            "items": [],
            "failures": [
                {"path": "old.png", "message": "failed"}
            ],
            "elapsed_ms": 1,
        }
        with self.assertRaises(ImportPayloadError):
            controller.prepare(base, ("new.png",))
        base["requested_paths"] = ("new.png",)
        base["failures"] = []
        with self.assertRaises(ImportPayloadError):
            controller.prepare(base, ("new.png",))


class HiddenTkImportLifecycleTests(unittest.TestCase):
    def _app(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        app = ISPApplication(root)
        deadline = time.time() + 6.0
        while time.time() < deadline and not app.results:
            root.update()
            time.sleep(0.01)
        return root, app

    def test_single_standard_image_uses_background_import(self):
        root, app = self._app()
        temporary = tempfile.TemporaryDirectory()
        try:
            path = Path(temporary.name) / "single.png"
            Image.new("RGB", (32, 24), (20, 40, 60)).save(path)
            app._load_paths([str(path)])
            self.assertIsNotNone(app.import_future)
            deadline = time.time() + 6.0
            while time.time() < deadline:
                root.update()
                if app.work_items[0].loaded.source_path == path:
                    break
                time.sleep(0.01)
            self.assertEqual(app.work_items[0].loaded.source_path, path)
            counters = app.performance.snapshot()["counters"]
            self.assertGreaterEqual(counters["import_tasks_completed"], 1)
            self.assertGreaterEqual(counters["import_files_succeeded"], 1)
        finally:
            temporary.cleanup()
            if root.winfo_exists():
                app.close()

    def test_stale_completed_batch_cannot_replace_workspace(self):
        root, app = self._app()
        temporary = tempfile.TemporaryDirectory()
        try:
            path = Path(temporary.name) / "stale.png"
            Image.new("RGB", (16, 12), (90, 20, 10)).save(path)
            payload = app._compute_import_payload(
                [str(path)],
                None,
                app.pipeline.snapshot(),
                None,
                app.preview_max_side,
            )
            old_generation = app.import_requests.begin()
            app.import_requests.begin()
            future = Future()
            future.set_result(payload)
            original_item = app.work_items[0]
            app._poll_image_import(
                future, old_generation, (str(path),)
            )
            self.assertIs(app.work_items[0], original_item)
            counters = app.performance.snapshot()["counters"]
            self.assertGreaterEqual(counters["import_results_stale"], 1)
        finally:
            temporary.cleanup()
            if root.winfo_exists():
                app.close()

    def test_worker_reports_each_file_as_success_or_failure(self):
        root, app = self._app()
        temporary = tempfile.TemporaryDirectory()
        try:
            good = Path(temporary.name) / "good.png"
            missing = Path(temporary.name) / "missing.png"
            Image.new("RGB", (8, 8), (1, 2, 3)).save(good)
            paths = (str(good), str(missing))
            payload = app._compute_import_payload(
                paths,
                None,
                app.pipeline.snapshot(),
                None,
                app.preview_max_side,
            )
            prepared = app.import_result_application.prepare(
                payload, paths
            )
            self.assertEqual((prepared.succeeded, prepared.failed), (1, 1))
            self.assertIn("missing.png", prepared.failure_messages[0])
        finally:
            temporary.cleanup()
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0436(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 36),
        )


if __name__ == "__main__":
    unittest.main()
