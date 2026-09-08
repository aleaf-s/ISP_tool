from concurrent.futures import Future
import time
import tkinter as tk
import unittest

from isp_tool import __version__
from isp_tool.ui.app import ISPApplication
from isp_tool.ui.controllers import (
    ACTION_APPLY,
    ACTION_CANCELLED,
    ACTION_STALE,
    ACTION_WAIT,
    AnalysisPayloadError,
    AnalysisRequestCoordinator,
    AnalysisResultApplicationController,
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


class AnalysisControllerTests(unittest.TestCase):
    def test_latest_schedule_supersedes_debounce_and_worker(self):
        scheduler = FakeScheduler()
        superseded = []
        coordinator = AnalysisRequestCoordinator(
            scheduler,
            on_request_superseded=lambda: superseded.append(1),
        )
        started = []
        first_generation = coordinator.schedule(
            lambda generation: started.append(generation)
        )
        first_after = coordinator.pending_after
        second_generation = coordinator.schedule(
            lambda generation: started.append(generation)
        )
        self.assertGreater(second_generation, first_generation)
        self.assertIn(first_after, scheduler.cancelled)
        self.assertEqual(len(superseded), 1)
        scheduler.run(coordinator.pending_after)
        self.assertEqual(started, [second_generation])

        future = RunningFuture()
        coordinator.bind_future(future)
        third_generation = coordinator.schedule(lambda _generation: None)
        self.assertGreater(third_generation, second_generation)
        self.assertEqual(future.cancel_calls, 1)
        self.assertIsNone(coordinator.current_future)
        self.assertEqual(len(superseded), 2)

    def test_poll_registration_and_close_are_centralized(self):
        scheduler = FakeScheduler()
        coordinator = AnalysisRequestCoordinator(scheduler)
        called = []
        coordinator.schedule_poll(lambda: called.append(True))
        callback_id = next(iter(coordinator.poll_after_ids))
        scheduler.run(callback_id)
        self.assertEqual(called, [True])
        self.assertFalse(coordinator.poll_after_ids)
        coordinator.schedule(lambda _generation: None)
        pending = coordinator.pending_after
        coordinator.close()
        self.assertTrue(coordinator.closed)
        self.assertIn(pending, scheduler.cancelled)

    def test_result_decision_prioritizes_stale_context(self):
        controller = AnalysisResultApplicationController()
        self.assertEqual(
            controller.decide(
                is_current=False,
                context_valid=True,
                done=False,
            ),
            ACTION_STALE,
        )
        self.assertEqual(
            controller.decide(
                is_current=True,
                context_valid=True,
                done=False,
            ),
            ACTION_WAIT,
        )
        self.assertEqual(
            controller.decide(
                is_current=True,
                context_valid=True,
                done=True,
                cancelled=True,
            ),
            ACTION_CANCELLED,
        )
        self.assertEqual(
            controller.decide(
                is_current=True,
                context_valid=True,
                done=True,
            ),
            ACTION_APPLY,
        )

    def test_payload_contract_rejects_missing_or_invalid_elapsed(self):
        controller = AnalysisResultApplicationController()
        prepared = controller.prepare({"value": {"ok": True}, "elapsed_ms": 2})
        self.assertEqual(prepared.elapsed_ms, 2.0)
        with self.assertRaises(AnalysisPayloadError):
            controller.prepare({"value": {}})
        with self.assertRaises(AnalysisPayloadError):
            controller.prepare({"value": {}, "elapsed_ms": -1})
        with self.assertRaises(AnalysisPayloadError):
            controller.prepare({"value": None, "elapsed_ms": 1})


class HiddenTkAnalysisLifecycleTests(unittest.TestCase):
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

    def test_stale_worker_payload_is_not_written_to_analysis_cache(self):
        root, app = self._app()
        try:
            app.analysis_collapsed = False
            generation = app.analysis_generation
            app.analysis_generation += 1
            key = ("stale-analysis",)
            future = Future()
            future.set_result({"value": {"old": True}, "elapsed_ms": 1.0})
            analysis_type = app._active_analysis_type()
            index = app._analysis_result_index(analysis_type)
            app._schedule_analysis_poll(
                future, generation, key, analysis_type, index
            )
            deadline = time.time() + 1.0
            while time.time() < deadline:
                root.update()
                counters = app.performance.snapshot()["counters"]
                if counters.get("analysis_results_stale", 0):
                    break
                time.sleep(0.01)
            self.assertIsNone(app.render_cache.get_analysis(key))
            counters = app.performance.snapshot()["counters"]
            self.assertGreaterEqual(
                counters.get("analysis_results_stale", 0), 1
            )
        finally:
            if root.winfo_exists():
                app.close()

    def test_histogram_uses_validated_cache_payload_and_closes_cleanly(self):
        root, app = self._app()
        try:
            app.open_histogram_window()
            histogram = app.histogram_window
            deadline = time.time() + 6.0
            while time.time() < deadline and histogram.last_payload is None:
                root.update()
                time.sleep(0.01)
            self.assertIsNotNone(histogram.last_payload)
            cached = next(iter(histogram.cache.values()))
            self.assertIn("value", cached)
            self.assertIn("elapsed_ms", cached)
            histogram.close()
            self.assertTrue(histogram.requests.closed)
            self.assertFalse(histogram.requests.poll_after_ids)
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_v0435(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 35)
        )


if __name__ == "__main__":
    unittest.main()
