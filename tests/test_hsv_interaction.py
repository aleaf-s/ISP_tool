"""Stable HSV wheel geometry, sidebar layout and non-destructive pick navigation."""
from types import SimpleNamespace
from pathlib import Path
import tempfile
from unittest import TestCase, mock
from tests import test_v0460
from isp_tool.grading.hsv_grid import HSVGrid, locate, load_hsv, export_hsv


class HSVInteractionTests(TestCase):
    setUp=test_v0460.HSVOnlyWorkspaceTests.setUp
    tearDown=test_v0460.HSVOnlyWorkspaceTests.tearDown
    wait_preview=test_v0460.HSVOnlyWorkspaceTests.wait_preview
    enter=test_v0460.HSVOnlyWorkspaceTests.enter

    def test_sidebar_and_header_layout(self):
        e=self.enter();p=self.panel
        p.open_clut_window();p.clut_window.geometry('1100x800');self.root.update()
        self.assertGreater(e.side_view.winfo_rootx(),e.notebook.winfo_rootx())
        self.assertLessEqual(e.notebook.winfo_rootx()+e.notebook.winfo_width(),e.side_view.winfo_rootx())
        self.assertLess(e.parameter_header.winfo_rooty(),e.notebook.winfo_rooty())
        self.assertIs(p.hsv_footer.master,e.sidebar)
        self.assertGreater(e.notebook.winfo_height(),200)

    def test_repeated_drag_position_has_no_scale_feedback_and_mesh_follows(self):
        e=self.enter();e.select_node(4,11)
        x,y=e.point_xy(4,11,e.state.grid)
        e.wheel_press(SimpleNamespace(x=x+2,y=y+1))
        scale=e.wheel_smax();geometry=e.wheel_geometry()
        event=SimpleNamespace(x=x+42,y=y-20)
        e.wheel_drag(event);first=e._drag_preview
        for _ in range(3):e.wheel_drag(event)
        self.assertEqual(first,e._drag_preview)
        self.assertEqual(scale,e.wheel_smax());self.assertEqual(geometry,e.wheel_geometry())
        px,py=e.point_xy(4,11,first)
        self.assertAlmostEqual(px,event.x-2);self.assertAlmostEqual(py,event.y-1)
        coords=e.wheel.coords('mesh-4-10')
        self.assertAlmostEqual(coords[-2],px);self.assertAlmostEqual(coords[-1],py)
        self.assertEqual(float(e.wheel.itemcget('mesh-4-10','width')),2)
        self.assertEqual(e.state.grid,HSVGrid())
        e.wheel_release();self.assertEqual(e.state.grid,first)

    def test_seam_selection_is_stable(self):
        e=self.enter();e.select_node(24,8)
        x,y=e.point_xy(24,8,e.state.grid)
        e.wheel_press(SimpleNamespace(x=x,y=y))
        self.assertEqual(e.state.selected,(24,8));e.wheel_release()

    def test_pick_preserves_imported_parameters_and_center_layer(self):
        e=self.enter();p=self.panel
        grid=HSVGrid().patch('dh',4,3,[[12]],4)
        p.clut_changed(grid,True)
        before=e.state.grid.targets;history=len(e.state.undo_stack)
        with mock.patch.object(p,'open_clut_window'):
            p.pick_clut_at(20,20)
            self.assertEqual(e.state.slice_index,4)
            self.assertEqual(e.state.grid.targets,before)
            self.assertEqual(e.state.grid.plane(4).dh[4*12+3],12)
            p.pick_clut_at(20,20)
        self.assertEqual(e.state.slice_index,4)
        self.assertEqual(e.state.grid.targets,before)
        self.assertEqual(len(e.state.undo_stack),history)

    def test_real_hisi_file_unchanged_after_picking_and_export(self):
        path=test_v0460.SAMPLE
        if not path.exists():self.skipTest('User fixture unavailable')
        e=self.enter();p=self.panel
        p.clut_changed(load_hsv(path),True)
        before=e.state.grid
        with mock.patch.object(p,'open_clut_window'):
            for _ in range(3):p.pick_clut_at(20,20)
        self.assertEqual(before,e.state.grid)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'out.txt';export_hsv(out,e.state.grid)
            self.assertEqual(out.read_bytes(),path.read_bytes())
