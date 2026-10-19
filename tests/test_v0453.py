"""CLUT pick, neighborhood editing, display-only mask and snapshot restore."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase,mock,skip
import numpy as np
from PIL import Image
from isp_tool.grading.clut import (HSGrid,neighbor_weights,edit_neighborhood,locate_rgb_node,
                                  sample_hs_field,load_parameters,apply_clut,build_clut)
from isp_tool.grading.image_io import ColorDocument,export_processed_image
from isp_tool.grading.model import raster8
from tests import test_v0444


class NeighborhoodTests(TestCase):
    def test_zero_radius_and_periodic_neighbors(self):
        single=edit_neighborhood(HSGrid(),0,4,10,.1)
        self.assertEqual(np.count_nonzero(single.dh),1)
        grid=edit_neighborhood(HSGrid(),0,4,10,.1,2,1)
        a=np.array(grid.dh).reshape(24,9)
        self.assertEqual(a[0,4],10);self.assertEqual(a[1,4],a[23,4])
        self.assertTrue(0<a[1,4]<10);self.assertEqual(a[2,4],0)
        self.assertTrue(np.all(a[:,0]==0))

    def test_smoothness_and_seam_and_neutral(self):
        a=neighbor_weights(0,4,3,0);b=neighbor_weights(0,4,3,1)
        self.assertEqual(a[0,4],1);self.assertEqual(b[0,4],1)
        self.assertGreater(b[1,4],a[1,4]);self.assertLess(b[2,4],a[2,4])
        self.assertFalse(neighbor_weights(0,0,6,1).any())
        hsv=np.array([[[359.999,.5,.8],[.001,.5,.8]]],np.float32)
        w=sample_hs_field(hsv,b)
        self.assertAlmostEqual(float(w[0,0]),float(w[0,1]),places=5)

    def test_validation_is_atomic_and_hue_uses_shortest_path(self):
        start=HSGrid().patch('ds',1,4,[[.99]])
        with self.assertRaises(ValueError):edit_neighborhood(start,0,4,10,.1,3,1)
        self.assertEqual(start.ds[13],.99)
        for radius,smooth in [(-1,1),(7,1),(2,float('nan'))]:
            with self.assertRaises(ValueError):neighbor_weights(0,4,radius,smooth)
        start=HSGrid().patch('dh',0,4,[[179]])
        result=edit_neighborhood(start,0,4,-179,0,2,1)
        self.assertEqual(result.dh[4],-179);self.assertAlmostEqual(result.dh[13],1)

    def test_rgb_location_and_low_chroma(self):
        self.assertEqual(locate_rgb_node((1,0,0)),(0,8))
        self.assertEqual(locate_rgb_node((0,1,0)),(8,8))
        self.assertEqual(locate_rgb_node((0,0,1)),(16,8))
        self.assertEqual(locate_rgb_node((.5,.5,.5)),(0,0))
        self.assertEqual(locate_rgb_node((0,0,0)),(0,0))


@skip('V0.4.60 已移除旧 HS/JSON 界面；HSV 取色、邻域和状态隔离回归见 test_v0457/test_v0460')
class CLUTWorkflowTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def editor(self):
        p=self.panel;p.method.set('CLUT 调色');p.switch_method();self.wait_preview()
        return p.clut_editor

    def test_pick_uses_original_and_does_not_change_grid(self):
        p=self.panel;e=self.editor();revision=p.revision
        p.source[:]=(.1,.1,.9)  # Proxy is deliberately unlike the full source.
        with mock.patch.object(p,'open_clut_window'):
            self.assertTrue(p.pick_clut_at(20,20))
        np.testing.assert_allclose(e.state.sample_rgb,(.8,.2,.1))
        self.assertEqual(e.state.selected,locate_rgb_node((.8,.2,.1)))
        self.assertEqual(e.state.grid,HSGrid());self.assertEqual(p.revision,revision)
        self.assertTrue(e.samples.find_all())

    def test_pick_preserves_drafts_and_refuses_transparency(self):
        p=self.panel;e=self.editor();e.variables[0].set('-')
        p.document.alpha=np.zeros(p.document.rgb.shape[:2],np.float32)
        self.assertFalse(p.pick_clut_at(10,10));self.assertIsNone(e.state.sample_rgb)
        p.document.alpha=None
        with mock.patch.object(p,'open_clut_window'):p.pick_clut_at(10,10)
        self.assertEqual(e.state.drafts[(0,4)][0],'-')

    def test_numeric_neighborhood_and_drag_remain_apply_only(self):
        p=self.panel;e=self.editor();revision=p.revision
        e.radius_var.set('2');e.smooth_var.set('1');e.brush_changed()
        e.variables[0].set('20');e.commit_node()
        self.assertEqual(e.state.grid.dh[13],10);self.assertEqual(p.revision,revision)
        self.assertEqual(e.state.applied_grid,HSGrid())
        before=e.state.grid;x,y=e.point_xy(0,4,before)
        e.wheel_press(SimpleNamespace(x=x,y=y));e.wheel_drag(SimpleNamespace(x=x,y=y-15));e.wheel_release()
        self.assertNotEqual(e.state.grid.dh[13],before.dh[13]);self.assertEqual(p.revision,revision)

    def test_restore_drops_invalid_text_and_retains_applied_output(self):
        p=self.panel;e=self.editor();applied=HSGrid().patch('dh',0,4,[[20]])
        p.clut_changed(applied,True);p.apply_clut_parameters();self.wait_preview()
        before=p.output.copy();revision=p.revision
        e.variables[0].set('60');e.commit_node();e.variables[1].set('-')
        p.restore_clut_applied()
        self.assertEqual(e.state.grid,applied);self.assertFalse(e.state.drafts)
        self.assertEqual(e.variables[0].get(),'20');self.assertEqual(p.clut_status.get(),'已应用')
        np.testing.assert_array_equal(p.output,before);self.assertEqual(p.revision,revision)

    def test_overlay_is_cached_and_never_enters_export(self):
        p=self.panel;e=self.editor();e.select_node(*locate_rgb_node((.8,.2,.1)))
        e.state.radius=3;e.state.show_influence=True;p.zoom=1;p.offset=[0,0]
        base=Image.fromarray(raster8(p.source));original=np.asarray(base).copy()
        painted,_=p.decorate_comparison_views(base,base)
        self.assertFalse(np.array_equal(painted,base));np.testing.assert_array_equal(base,original)
        cached=p._influence_cache;p.decorate_comparison_views(base,base)
        self.assertIs(p._influence_cache,cached)
        revision=p.revision;e.state.radius=2;p.decorate_comparison_views(base,base)
        self.assertIsNot(p._influence_cache,cached);self.assertEqual(p.revision,revision)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'result.png';export_processed_image(path,p.document,p.preview_processor())
            with Image.open(path) as image:np.testing.assert_array_equal(image,raster8(p.document.rgb))
        p.hold_original=True;plain,_=p.decorate_comparison_views(base,base)
        self.assertIs(plain,base)

    def test_scheme_saves_valid_pending_numbers_without_applying(self):
        p=self.panel;e=self.editor();revision=p.revision;e.variables[0].set('15')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'scheme.json'
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(path)):
                p.save_clut_parameters()
            self.assertEqual(load_parameters(path)[0].dh[4],15)
        self.assertEqual(e.state.applied_grid,HSGrid());self.assertEqual(p.revision,revision)

    def test_restore_and_sample_are_isolated_between_images(self):
        p=self.panel;e=self.editor();a=p.document
        with mock.patch.object(p,'open_clut_window'):p.pick_clut_at(10,10)
        p.clut_changed(HSGrid().patch('dh',0,4,[[15]]),True)
        p.documents.append(ColorDocument('B.png',a.rgb.copy(),None,8,'sRGB'));p.select_document(1);self.wait_preview();self.editor()
        self.assertIsNone(e.state.sample_rgb);p.restore_clut_applied()
        self.assertEqual(p.state_for(a).clut.grid.dh[4],15)
        p.select_document(0);self.wait_preview();self.assertIsNotNone(e.state.sample_rgb)

    def test_split_drag_has_priority_over_clut_picking(self):
        p=self.panel;self.editor();p.pick.set(True);p.divider=.5
        with mock.patch.object(p,'pick_clut_at') as pick:
            p.press(SimpleNamespace(x=p.canvas.winfo_width()*.5,y=20))
            pick.assert_not_called();self.assertEqual(p.drag,('split',))
