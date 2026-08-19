import tkinter as tk
import unittest

from isp_tool import __version__
from isp_tool.models import CalibrationSession
from isp_tool.raw_io import synthetic_bayer
from isp_tool.ui.app import ISPApplication
from isp_tool.workspace import ImageWorkItem, RuntimePreviewState
from isp_tool.workspace_cache import (
    CACHE_HIT,
    CACHE_INVALID,
    CACHE_MISS,
    PreviewCacheContext,
    WorkspacePreviewCachePolicy,
)


def make_item(memory_bytes=100, last_used=0):
    loaded = synthetic_bayer(8, 8)
    item = ImageWorkItem(
        loaded,
        [],
        CalibrationSession(raw_metadata=loaded.metadata),
    )
    item.runtime_preview = RuntimePreviewState(
        preview_quality="Balanced",
        preview_max_side=1200,
        backend_cache_key="opencv",
        preview_image=loaded.image,
        pipeline_snapshot=[],
        pipeline_cache={"results": [object()]},
        results=[object()],
        input_revision=0,
        image_identity=id(loaded.image),
        memory_bytes=memory_bytes,
        last_used=last_used,
    )
    return item


def context_for(item, quality="Balanced"):
    return PreviewCacheContext(
        quality,
        1200,
        "opencv",
        item.input_revision,
        id(item.loaded.image),
        item.pipeline_snapshot,
    )


class WorkspacePreviewCachePolicyTests(unittest.TestCase):
    def test_summary_reports_count_memory_and_limits(self):
        policy = WorkspacePreviewCachePolicy(3, 1024)
        items = [make_item(100), make_item(250), make_item(75)]
        summary = policy.summary(items)
        self.assertEqual(summary.count, 3)
        self.assertEqual(summary.memory_bytes, 425)
        self.assertEqual(summary.max_items, 3)
        self.assertFalse(summary.over_budget)

    def test_capacity_evicts_oldest_with_stable_index_tie_break(self):
        policy = WorkspacePreviewCachePolicy(2, 10_000)
        items = [make_item(100, 1), make_item(100, 1), make_item(100, 3)]
        evicted = policy.trim(items, protected_item=items[2])
        self.assertEqual(evicted, [items[0]])
        self.assertIsNone(items[0].runtime_preview)
        self.assertIsNotNone(items[1].runtime_preview)

    def test_budget_evicts_until_within_limit(self):
        policy = WorkspacePreviewCachePolicy(3, 150)
        items = [make_item(100, 1), make_item(100, 2), make_item(100, 3)]
        evicted = policy.trim(items, protected_item=items[2])
        self.assertEqual(evicted, [items[0], items[1]])
        self.assertLessEqual(policy.summary(items).memory_bytes, 150)

    def test_oversized_protected_entry_is_retained(self):
        policy = WorkspacePreviewCachePolicy(1, 50)
        item = make_item(200, 1)
        self.assertEqual(policy.trim([item], protected_item=item), [])
        self.assertIsNotNone(item.runtime_preview)
        self.assertTrue(policy.summary([item]).over_budget)

    def test_lookup_distinguishes_miss_invalid_and_hit(self):
        policy = WorkspacePreviewCachePolicy()
        missing = make_item()
        missing.runtime_preview = None
        self.assertEqual(
            policy.lookup(missing, context_for(missing)).status,
            CACHE_MISS,
        )
        invalid = make_item()
        result = policy.lookup(
            invalid, context_for(invalid, quality="Fine")
        )
        self.assertEqual(result.status, CACHE_INVALID)
        self.assertIsNone(invalid.runtime_preview)
        valid = make_item(last_used=5)
        result = policy.lookup(valid, context_for(valid))
        self.assertEqual(result.status, CACHE_HIT)
        self.assertIs(result.state, valid.runtime_preview)
        self.assertGreater(result.state.last_used, 5)

    def test_put_touches_new_entry_and_protects_it(self):
        policy = WorkspacePreviewCachePolicy(1, 10_000)
        old_item = make_item(100, 1)
        new_item = make_item(100, 0)
        state = new_item.runtime_preview
        new_item.runtime_preview = None
        evicted = policy.put(
            new_item,
            state,
            [old_item, new_item],
            protected_item=new_item,
        )
        self.assertEqual(evicted, [old_item])
        self.assertIs(new_item.runtime_preview, state)
        self.assertGreater(state.last_used, 0)

    def test_clear_returns_released_entry_count(self):
        policy = WorkspacePreviewCachePolicy()
        items = [make_item(), make_item(), make_item()]
        items[1].runtime_preview = None
        self.assertEqual(policy.clear(items), 2)
        self.assertTrue(all(item.runtime_preview is None for item in items))


class HiddenTkCacheCompatibilityTests(unittest.TestCase):
    def test_legacy_limits_proxy_policy_without_processing(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        app = ISPApplication(root)
        try:
            generation = app.generation
            app.runtime_cache_max_items = 2
            app.runtime_cache_budget_bytes = 64 * 1024 * 1024
            self.assertEqual(
                app.runtime_preview_cache_policy.max_items, 2
            )
            self.assertEqual(
                app.runtime_preview_cache_policy.budget_bytes,
                64 * 1024 * 1024,
            )
            self.assertEqual(app.generation, generation)
        finally:
            app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0431(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))), (0, 4, 31)
        )


if __name__ == "__main__":
    unittest.main()
