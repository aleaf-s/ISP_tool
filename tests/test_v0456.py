"""CA usable controls, device TXT import and exact data-count regression."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock, skip
import tempfile
import time
import tkinter as tk
import numpy as np
from isp_tool.grading.clut import HSGrid, build_clut, apply_clut, edit_neighborhood
from isp_tool.grading.hisi_clut import load_hisi, export_hisi, read_words, pack_deltas
from isp_tool.grading.ca import CAState, CACurve, load_ca_text, export_ca_text
from isp_tool.ui.widgets.ca_editor import CAEditor
from tests import test_v0444


class DeviceDataTests(TestCase):
    def test_device_exact_roundtrip_and_actual_transform(self):
        delta=np.zeros((17,17,17,3),np.int16);delta[...,0]=30
        words=tuple(int(v) for v in pack_deltas(delta))
        grid=HSGrid(base_words=words)
        rgb=np.array([[[.3,.4,.5]]],np.float32)
        np.testing.assert_allclose(apply_clut(rgb,build_clut(grid)),rgb+[[[30/1023,0,0]]],atol=1e-7)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'clut.txt';export_hisi(path,grid)
            self.assertEqual(len(read_words(path)),5508)
            self.assertEqual(load_hisi(path),grid)
            self.assertEqual(tuple(int(v) for v in read_words(path)),words)
            edited=edit_neighborhood(grid,4,4,5,.01)
            self.assertEqual(edited.base_words,words)
            self.assertEqual(edited.patch('ds',3,3,[[.02]]).base_words,words)
            export_hisi(path,edited)
            self.assertEqual(len(read_words(path)),5508)
            self.assertFalse(np.array_equal(read_words(path),words))

    def test_supplied_samples_roundtrip(self):
        clut=Path('D:/Rroject_Remo_AWB/01_Param/02_Hisi/CLUT/lantian_caodi.txt')
        ca=Path('C:/Users/remo/Downloads/Chroma_Adjust_Data_DEC_20260923202822.txt')
        if not clut.exists() or not ca.exists():self.skipTest('Local reference files unavailable')
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'clut.txt';export_hisi(out,load_hisi(clut))
            np.testing.assert_array_equal(read_words(out),read_words(clut))
            self.assertEqual(len(read_words(out)),5508)
            out=Path(folder)/'ca.txt';export_ca_text(out,load_ca_text(ca))
            self.assertEqual(out.read_bytes(),ca.read_bytes())
            self.assertEqual(len(load_ca_text(out).values),256)


class InteractionTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def enter_ca(self):
        p=self.panel;p.method.set('CA 调色');p.switch_method();self.wait_preview()
        return p.ca_editor

    def test_add_delete_duplicate_and_undo_selection(self):
        e=self.enter_ca();revision=self.panel.revision
        e.x_var.set('130');e.y_var.set('1450');self.assertTrue(e.add_point())
        self.assertEqual(len(e.state.curve.points),18);self.assertEqual(e.state.selected_x,130)
        self.assertIn('18 / 64',e.count.get());self.assertFalse(e.add_point())
        self.assertTrue(self.panel.error.get());self.assertEqual(len(e.state.curve.points),18)
        e.delete_point();self.assertEqual(len(e.state.curve.points),17)
        e.travel(False);self.assertEqual(len(e.state.curve.points),18)
        e.travel(False);self.assertEqual(len(e.state.curve.points),17)
        self.assertIn(e.state.selected_x,dict(e.state.curve.points))
        e.state.selected_x=0;e.show_selection();self.assertTrue(e.delete_button.instate(['disabled']))
        self.assertEqual(self.panel.revision,revision);self.assertEqual(len(e.state.curve.values),256)

    def test_double_click_add_drag_and_apply(self):
        e=self.enter_ca();self.panel.ca_window.deiconify();self.root.update()
        px,py=e.point_xy(135,1400)
        e.double_click(SimpleNamespace(x=px,y=py))
        self.assertEqual(e.state.selected_x,135)
        self.assertEqual(len(e.state.curve.points),18)
        px,py=e.point_xy(135,e.state.curve.values[135]);e.press(SimpleNamespace(x=px,y=py))
        _,py=e.point_xy(135,1600);e.drag(SimpleNamespace(y=py));e.release()
        self.assertEqual(e.state.curve.values[135],1600)
        self.assertEqual(e.state.applied,CACurve())
        self.panel.apply_ca_parameters();self.wait_preview()
        self.assertEqual(e.state.applied.values[135],1600)
        old=e.state.curve
        px,py=e.point_xy(135,1100);e.double_click(SimpleNamespace(x=px,y=py))
        self.assertEqual(e.state.curve,old);self.assertIsNone(e.state.drafts)
        e.canvas.focus_force();e.canvas.event_generate('<Delete>');self.root.update()
        self.assertNotIn(135,dict(e.state.curve.points))
        self.assertEqual(e.state.applied.values[135],1600)

    def test_focus_loss_commits_y_without_enter(self):
        e=self.enter_ca();self.panel.ca_window.deiconify();self.root.update()
        e.canvas.focus_force();e.y_var.set('1400');e.focus_out();self.root.update()
        self.assertEqual(e.state.curve.values[128],1400)
        self.assertEqual(e.state.applied,CACurve())
        e.y_var.set('-');e.focus_out();self.root.update()
        self.assertEqual(e.state.curve.values[128],1400);self.assertTrue(self.panel.error.get())

    def test_x_queries_curve_and_right_click_removes(self):
        e=self.enter_ca()
        e.y_var.set('1700');e.set_point()
        e.x_var.set('132');self.assertTrue(e.query_x())
        self.assertEqual(int(e.y_var.get()),e.state.curve.values[132])
        self.assertTrue(e.add_point());self.assertIn(132,dict(e.state.curve.points))
        px,py=e.point_xy(132,e.state.curve.values[132]);e.right_click(SimpleNamespace(x=px,y=py))
        self.assertNotIn(132,dict(e.state.curve.points))
        self.assertEqual(e.state.applied,CACurve())

    @skip('V0.4.60 移除设备 CLUT 的界面导入/导出；HSV 原子导入与恢复见 test_v0460')
    def test_txt_import_apply_export_invalid_atomicity_and_reset(self):
        p=self.panel;p.method.set('CLUT 调色');p.switch_method();self.wait_preview()
        delta=np.zeros((17,17,17,3),np.int16);delta[...,2]=40
        base=HSGrid(base_words=tuple(int(v) for v in pack_deltas(delta)))
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.txt';dest=Path(folder)/'out.txt';export_hisi(source,base)
            revision=p.revision
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(source)):
                p.load_clut_file()
            state=p.state_for(p.document).clut
            self.assertEqual(state.device_grid,base);self.assertEqual(state.grid,HSGrid());self.assertEqual(state.applied_grid,HSGrid())
            self.assertEqual(p.revision,revision)
            p.apply_clut_parameters();self.wait_preview()
            np.testing.assert_allclose(p.preview_processor()(p.document.rgb),apply_clut(p.document.rgb,build_clut(base)))
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(dest)):
                p.export_clut_file()
            until=time.monotonic()+8
            while p.io_future is not None and time.monotonic()<until:
                self.root.update();time.sleep(.01)
            np.testing.assert_array_equal(read_words(dest),read_words(source))
            source.write_text('1,2,3')
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(source)),mock.patch('isp_tool.ui.grading_workspace.messagebox.askyesno',return_value=True):
                p.load_clut_file()
            self.assertEqual(state.device_grid,base);self.assertTrue(p.error.get())
            p.clut_editor.reset_all();self.assertEqual(state.device_grid,base)


class LayoutTests(TestCase):
    def test_ca_controls_accessible_at_multiple_scales(self):
        for scale in (1.0,1.5,2.0):
            root=tk.Tk();root.withdraw();root.tk.call('tk','scaling',scale)
            try:
                state=CAState();error=tk.StringVar(root)
                e=CAEditor(root,state.replace,lambda:None,lambda:None,lambda:None,lambda:None,error)
                e.pack(fill='both',expand=True);e.set_state(state)
                root.update_idletasks()
                width=max(640,e.side.winfo_reqwidth()+320)
                for height in (420,700):
                    root.geometry(f'{width}x{height}');root.deiconify();root.update()
                    self.assertGreater(e.canvas.winfo_width(),200)
                    self.assertGreaterEqual(e.side_canvas.winfo_width(),e.side.winfo_reqwidth())
                    bottom=e.apply_button.winfo_rooty()+e.apply_button.winfo_height()
                    self.assertLessEqual(bottom,root.winfo_rooty()+root.winfo_height())
                    e.side_canvas.yview_moveto(1);root.update()
                    self.assertAlmostEqual(e.side_canvas.yview()[1],1,places=2)
            finally:root.destroy()
