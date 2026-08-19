import unittest
from types import SimpleNamespace

import numpy as np

from isp_tool import __version__
from isp_tool.models import StageResult
from isp_tool.ui.controllers import (
    ACTION_APPLY,
    ACTION_CANCELLED,
    ACTION_STALE,
    ACTION_WAIT,
    PreviewPayloadError,
    PreviewResultApplicationController,
)


def result(name="Output"):
    return StageResult(
        "test", name, np.zeros((2, 2, 3), np.float32), "rgb", 0.0
    )


class PreviewResultApplicationControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = PreviewResultApplicationController()

    def test_stale_precedes_wait_and_cancelled(self):
        self.assertEqual(
            self.controller.decide(
                is_current=False, done=False, cancelled=True
            ),
            ACTION_STALE,
        )

    def test_wait_cancelled_and_apply_decisions(self):
        self.assertEqual(
            self.controller.decide(is_current=True, done=False),
            ACTION_WAIT,
        )
        self.assertEqual(
            self.controller.decide(
                is_current=True, done=True, cancelled=True
            ),
            ACTION_CANCELLED,
        )
        self.assertEqual(
            self.controller.decide(is_current=True, done=True),
            ACTION_APPLY,
        )

    def test_raw_payload_is_validated_and_metrics_are_copied(self):
        metrics = {"cache_hits": 1}
        prepared = self.controller.prepare_raw([result()], metrics)
        metrics["cache_hits"] = 9
        self.assertEqual(prepared.kind, "raw")
        self.assertEqual(prepared.metrics["cache_hits"], 1)
        self.assertEqual(len(prepared.results), 1)

    def test_raw_payload_rejects_empty_or_malformed_results(self):
        for payload in ([], [object()], {"results": []}):
            with self.subTest(payload=type(payload).__name__):
                with self.assertRaises(PreviewPayloadError):
                    self.controller.prepare_raw(payload)

    def test_yuv_payload_requires_all_contract_fields(self):
        with self.assertRaises(PreviewPayloadError):
            self.controller.prepare_yuv(
                {"frame": object()}, cached=False, cache_key=None
            )

    def test_yuv_cache_write_is_explicit_for_new_payload_only(self):
        frame = SimpleNamespace(
            metadata=SimpleNamespace(), frame_index=0
        )
        conversion = SimpleNamespace(
            rgb=np.zeros((2, 2, 3), np.float32)
        )
        payload = {
            "frame": frame,
            "conversion": conversion,
            "results": [result()],
            "metrics": {"recomputed": 3},
        }
        fresh = self.controller.prepare_yuv(
            payload, cached=False, cache_key=("frame", 0)
        )
        cached = self.controller.prepare_yuv(
            payload, cached=True, cache_key=("frame", 0)
        )
        self.assertEqual(fresh.cache_key_to_store, ("frame", 0))
        self.assertIsNone(cached.cache_key_to_store)
        self.assertIs(fresh.original_payload, payload)


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0433(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 33)
        )


if __name__ == "__main__":
    unittest.main()
