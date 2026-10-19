from dataclasses import replace
from pathlib import Path
import tempfile
from unittest import TestCase, mock
import numpy as np
from tests import test_v0460
from isp_tool.grading.hsv_grid import HSVGrid, SHAPE, load_hsv, export_hsv
from isp_tool.grading.clut import build_clut, apply_clut


class StrengthTests(TestCase):
    def test_effective_scaling_identity_clamp_and_unknown_preservation(self):
        base=HSVGrid().patch('dh',4,3,[[16]],4).patch('ds',4,3,[[-.2]],4).cover_center()
        half=replace(base,strength=.5).effective()
        self.assertAlmostEqual(half.plane(4).dh[51],8)
        self.assertAlmostEqual(half.plane(3).dh[51],8)
        self.assertAlmostEqual(half.plane(4).ds[51],-.1)
        self.assertEqual(replace(base,strength=0).effective().targets,HSVGrid().targets)
        a=np.array(base.targets).reshape(*SHAPE,3);a[0,0,0,2]=.01
        scaled=replace(base,targets=tuple(a.ravel()),strength=2).effective()
        self.assertEqual(scaled.targets[2],.01)
        self.assertAlmostEqual(scaled.plane(4).ds[51],-.319)
        self.assertEqual(scaled.effective(),scaled)
        for v in (-1,2.1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):replace(base,strength=v)

    def test_export_bakes_once_and_preview_matches_reload(self):
        base=HSVGrid().patch('dh',4,3,[[16]],4).cover_center()
        grid=replace(base,strength=.5)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'strength.txt';export_hsv(path,grid)
            loaded=load_hsv(path)
            self.assertEqual(loaded.strength,1)
            self.assertEqual(loaded.targets,grid.effective().targets)
            np.testing.assert_array_equal(build_clut(grid),build_clut(loaded))
            original=path.read_bytes();export_hsv(path,grid)
            self.assertEqual(original,path.read_bytes())


class StrengthWorkflowTests(TestCase):
    setUp=test_v0460.HSVOnlyWorkspaceTests.setUp
    tearDown=test_v0460.HSVOnlyWorkspaceTests.tearDown
    wait_preview=test_v0460.HSVOnlyWorkspaceTests.wait_preview
    enter=test_v0460.HSVOnlyWorkspaceTests.enter

    def test_apply_export_restore_and_no_compounding(self):
        e=self.enter();p=self.panel
        e.select_node(0,7);e.variables[0].set('20');e.commit_node()
        raw=e.state.grid.targets;revision=p.revision
        e.strength_var.set('.5');self.assertTrue(e.state.pending())
        e.commit_strength();self.assertEqual(p.revision,revision)
        self.assertEqual(e.state.grid.targets,raw)
        self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        np.testing.assert_allclose(p.output,apply_clut(p.document.rgb,build_clut(e.state.grid)),atol=1e-6)
        revision=p.revision
        self.assertTrue(p.apply_clut_parameters());self.assertEqual(p.revision,revision)
        e.strength_var.set('1.5');e.commit_strength()
        e.travel(False);self.assertEqual(e.state.grid.strength,.5)
        e.travel(True);self.assertEqual(e.state.grid.strength,1.5)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'out.txt'
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(path)):p.save_hsv_file()
            self.assertEqual(load_hsv(path).targets,e.state.grid.effective().targets)
        self.assertEqual(p.revision,revision)
        p.restore_clut_applied();self.assertEqual(e.strength_var.get(),'0.5')
        self.assertFalse(e.state.pending())

    def test_invalid_strength_blocks_atomic_commit(self):
        e=self.enter();before=e.state.grid
        e.select_node(4,3);e.variables[0].set('16');e.strength_var.set('nan')
        self.assertFalse(e.commit_all());self.assertEqual(e.state.grid,before)
        self.assertIsNotNone(e.state.strength_draft)
        e.strength_var.set('1');self.assertTrue(e.commit_all())
        self.assertEqual(e.state.grid.plane(4).dh[51],16)
