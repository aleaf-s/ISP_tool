import time
import tkinter as tk
import unittest

import numpy as np

from isp_tool import __version__
from isp_tool.calibration.ccm_solver import (
    apply_ccm,
    solve_ccm_from_patches,
)
from isp_tool.models import ColorCheckerPatch


class SignedCCMTests(unittest.TestCase):
    def test_auto_ccm_uses_expected_signed_matrix_structure(self):
        rng = np.random.default_rng(416)
        measured = rng.uniform(0.06, 0.82, (24, 3))
        expected = np.array(
            [
                [1.18, -0.12, -0.06],
                [-0.08, 1.16, -0.08],
                [-0.05, -0.13, 1.18],
            ],
            dtype=np.float64,
        )
        reference = apply_ccm(
            measured,
            expected,
            np.array([0.005, -0.003, 0.008]),
        )
        patches = [
            ColorCheckerPatch(
                patch_id=index + 1,
                name=f"P{index + 1}",
                polygon=[],
                measured_rgb=measured[index],
                reference_rgb=reference[index],
                diagnostics={"valid": True, "reference_index": index},
            )
            for index in range(24)
        ]

        result = solve_ccm_from_patches(patches)

        self.assertTrue(np.all(np.diag(result.matrix) > 1.0))
        off_diagonal = result.matrix[~np.eye(3, dtype=bool)]
        self.assertGreaterEqual(np.count_nonzero(off_diagonal < 0.0), 4)
        self.assertLessEqual(
            result.diagnostics["positive_off_diagonal_count"],
            2,
        )
        np.testing.assert_allclose(
            result.matrix.sum(axis=1),
            np.ones(3),
            atol=0.08,
        )
        self.assertTrue(result.diagnostics["safe_to_apply"])


class HiddenTkDemosaicModeTests(unittest.TestCase):
    def _root(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        return root

    @staticmethod
    def _wait(root, condition, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            root.update()
            if condition():
                return
            time.sleep(0.01)
        raise AssertionError("condition timed out")

    def test_demosaic_hides_manual_auto_switch_and_forces_manual_panel(self):
        from isp_tool.ui.app import ISPApplication

        root = self._root()
        app = ISPApplication(root)
        try:
            self._wait(root, lambda: bool(app.results))
            demosaic_index = next(
                index
                for index, module in enumerate(app.pipeline.modules)
                if module.module_id == "demosaic"
            )
            app._set_adjustment_mode("auto")
            app.pipeline_list.selection_clear(0, "end")
            app.pipeline_list.selection_set(demosaic_index)
            app._on_module_select()
            root.update_idletasks()

            self.assertEqual(app.adjustment_mode, "manual")
            self.assertFalse(app.mode_switch.winfo_manager())
            self.assertTrue(app.manual_card.winfo_manager())

            ccm_index = next(
                index
                for index, module in enumerate(app.pipeline.modules)
                if module.module_id == "color_correction_matrix"
            )
            app.pipeline_list.selection_clear(0, "end")
            app.pipeline_list.selection_set(ccm_index)
            app._on_module_select()
            root.update_idletasks()
            self.assertTrue(app.mode_switch.winfo_manager())
        finally:
            if root.winfo_exists():
                app.close()


class VersionTests(unittest.TestCase):
    def test_version_is_at_least_v0416(self):
        self.assertGreaterEqual(
            tuple(map(int, __version__.split("."))),
            (0, 4, 16),
        )


if __name__ == "__main__":
    unittest.main()
