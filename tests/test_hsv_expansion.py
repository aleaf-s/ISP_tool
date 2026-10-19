"""All-V editing replaces the former optional brightness falloff."""
from dataclasses import replace
from pathlib import Path
import tempfile
from unittest import TestCase
import numpy as np
from tests import test_v0460
from isp_tool.grading.hsv_grid import HSVGrid, SHAPE, load_hsv, export_hsv, influence


class CoverageTests(TestCase):
    def test_overwrite_existing_layers_keep_opaque_fields_and_roundtrip(self):
        grid=HSVGrid().patch('dh',4,3,[[16]],4).patch('ds',4,3,[[.2]],4)
        grid=grid.patch('dh',4,3,[[7]],2)
        a=np.array(grid.targets).reshape(*SHAPE,3);a[6,4,3,2]=.01
        grid=replace(grid,targets=tuple(a.ravel()))
        out=grid.cover_center();b=np.array(out.targets).reshape(*SHAPE,3)
        for i in range(9):np.testing.assert_array_equal(b[i,...,:2],a[4,...,:2])
        np.testing.assert_array_equal(b[...,2],a[...,2])
        self.assertEqual(out.cover_center(),out)
        changed=out.patch('dh',4,3,[[8]],4).cover_center()
        for i in range(9):self.assertAlmostEqual(changed.plane(i).dh[51],8)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'hsv.txt';export_hsv(path,changed)
            self.assertEqual(load_hsv(path).targets,changed.targets)

    def test_influence_has_equal_weight_at_all_brightnesses(self):
        hsv=np.array([[[60,.319,v] for v in np.linspace(0,1,21)]],np.float32)
        np.testing.assert_allclose(influence(hsv,4,4,3,0,1),1,atol=1e-6)


class CoverageWorkflowTests(TestCase):
    setUp=test_v0460.HSVOnlyWorkspaceTests.setUp
    tearDown=test_v0460.HSVOnlyWorkspaceTests.tearDown
    wait_preview=test_v0460.HSVOnlyWorkspaceTests.wait_preview
    enter=test_v0460.HSVOnlyWorkspaceTests.enter

    def test_auto_cover_edit_undo_apply_reset_and_paste(self):
        e=self.enter();p=self.panel;revision=p.revision
        self.assertFalse(hasattr(e,'expand_button'))
        e.select_node(4,3);e.variables[0].set('16');e.commit_node()
        first=e.state.grid
        for i in range(9):self.assertEqual(first.plane(i).dh[51],16)
        self.assertEqual(p.revision,revision)
        e.variables[0].set('8');e.commit_node();second=e.state.grid
        for i in range(9):self.assertEqual(second.plane(i).dh[51],8)
        e.travel(False);self.assertEqual(e.state.grid,first)
        e.travel(True);self.assertEqual(e.state.grid,second)
        self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        self.assertEqual(e.state.applied_grid,second)
        e.reset_selected()
        for i in range(9):self.assertEqual(e.state.grid.plane(i).dh[51],0)
        e.paste_cells('dh','10\t12')
        for i in range(9):self.assertEqual(e.state.grid.plane(i).dh[51:53],(10,12))
        e.reset_all();self.assertEqual(e.state.grid.targets,HSVGrid().targets)

    def test_neighborhood_overwrites_the_center_plane_across_all_v(self):
        e=self.enter();p=self.panel
        imported=HSVGrid().patch('dh',10,7,[[30]],0)
        p.clut_changed(imported,True)
        e.state.radius=2;e.select_node(4,3);e.variables[0].set('16');e.commit_node()
        planes=np.asarray(e.state.grid.targets).reshape(*SHAPE,3)
        for i in range(9):np.testing.assert_array_equal(planes[i,...,:2],planes[4,...,:2])
        self.assertEqual(e.state.grid.plane(0).dh[10*12+7],0)
        e.travel(False);self.assertEqual(e.state.grid,imported)

    def test_focus_only_commit_and_gain_change_do_not_cover_import(self):
        e=self.enter();p=self.panel
        imported=HSVGrid().patch('dh',10,7,[[30]],0)
        p.clut_changed(imported,True)
        self.assertTrue(e.commit_node());self.assertEqual(e.state.grid,imported)
        e.gain_vars[0].set('256');self.assertTrue(e.commit_gains())
        self.assertTrue(e.commit_all());self.assertEqual(e.state.grid.targets,imported.targets)
