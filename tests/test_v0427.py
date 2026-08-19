import unittest

from isp_tool import __version__
from isp_tool.ui.controllers import PreviewRequestCoordinator


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
        _, callback = self.callbacks.pop(callback_id)
        callback()


class FakeFuture:
    def __init__(self):
        self.is_done = False
        self.cancel_calls = 0

    def done(self):
        return self.is_done

    def cancel(self):
        self.cancel_calls += 1
        self.is_done = True
        return True


class PreviewRequestCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = FakeScheduler()
        self.dropped_requests = []
        self.dropped_results = []
        self.coordinator = PreviewRequestCoordinator(
            self.scheduler,
            on_request_dropped=lambda: self.dropped_requests.append(1),
            on_result_dropped=lambda: self.dropped_results.append(1),
        )

    def test_debounce_keeps_only_the_latest_start_callback(self):
        started = []
        self.coordinator.schedule(lambda: started.append("old"))
        old_id = self.coordinator.pending_after
        self.coordinator.schedule(lambda: started.append("new"))
        new_id = self.coordinator.pending_after

        self.assertNotEqual(old_id, new_id)
        self.assertIn(old_id, self.scheduler.cancelled)
        self.assertNotIn(old_id, self.scheduler.callbacks)
        self.scheduler.run(new_id)
        self.assertEqual(started, ["new"])
        self.assertIsNone(self.coordinator.pending_after)

    def test_begin_supersedes_worker_and_signals_cooperative_cancel(self):
        first = self.coordinator.begin()
        future = FakeFuture()
        self.coordinator.bind_future(future)
        second = self.coordinator.begin()

        self.assertTrue(first.cancel_event.is_set())
        self.assertFalse(second.cancel_event.is_set())
        self.assertEqual(second.generation, first.generation + 1)
        self.assertEqual(future.cancel_calls, 1)
        self.assertTrue(self.coordinator.is_current(second.generation))
        self.assertFalse(self.coordinator.is_current(first.generation))

    def test_explicit_cancel_counts_pending_and_queued_work(self):
        self.coordinator.schedule(lambda: None)
        token = self.coordinator.begin()
        # begin consumes the scheduled callback; add another pending callback
        # to exercise both cancellation paths in one explicit cancel.
        self.coordinator.schedule(lambda: None)
        future = FakeFuture()
        self.coordinator.bind_future(future)
        self.coordinator.cancel(count_drops=True)

        self.assertTrue(token.cancel_event.is_set())
        self.assertTrue(future.is_done)
        self.assertIsNone(self.coordinator.pending_after)
        self.assertEqual(len(self.dropped_requests), 2)

    def test_stale_result_notification_is_centralized(self):
        first = self.coordinator.begin()
        self.coordinator.begin()
        self.assertFalse(self.coordinator.is_current(first.generation))
        self.coordinator.reject_stale_result()
        self.assertEqual(self.dropped_results, [1])

    def test_poll_callback_is_unregistered_before_running(self):
        called = []
        self.coordinator.schedule_poll(lambda: called.append(True))
        callback_id = next(iter(self.coordinator.poll_after_ids))
        self.assertIn(callback_id, self.scheduler.callbacks)
        self.scheduler.run(callback_id)
        self.assertEqual(called, [True])
        self.assertNotIn(callback_id, self.coordinator.poll_after_ids)

    def test_close_cancels_all_callbacks_and_rejects_new_work(self):
        token = self.coordinator.begin()
        self.coordinator.schedule(lambda: None)
        self.coordinator.schedule_poll(lambda: None)
        callback_ids = {
            self.coordinator.pending_after,
            *self.coordinator.poll_after_ids,
        }
        self.coordinator.close()

        self.assertTrue(token.cancel_event.is_set())
        self.assertTrue(self.coordinator.closed)
        self.assertTrue(callback_ids.issubset(set(self.scheduler.cancelled)))
        self.assertEqual(self.coordinator.poll_after_ids, set())
        self.coordinator.schedule(lambda: self.fail("started after close"))
        self.assertIsNone(self.coordinator.pending_after)


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0427(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 27)
        )


if __name__ == "__main__":
    unittest.main()
