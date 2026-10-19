"""Independent HSV/device import, visible device values and selected preview source."""
from pathlib import Path
from dataclasses import replace
from unittest import TestCase, mock, skip
import tempfile
import time
import numpy as np
from isp_tool.grading.hsv_grid import HSVGrid, SHAPE, load_hsv, export_hsv
from isp_tool.grading.clut import HSGrid, apply_clut, build_clut
from isp_tool.grading.hisi_clut import pack_deltas, export_hisi, read_words
from isp_tool.grading.image_io import ColorDocument
from tests import test_v0444


class HSVBoundsTests(TestCase):
    def test_target_is_not_limited_by_input_axis(self):
        grid=HSVGrid().patch('ds',7,11,[[.009]],index=4)
        self.assertAlmostEqual(np.asarray(grid.targets).reshape(*SHAPE,3)[4,7,11,1],1.179)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'hsv.txt';export_hsv(path,grid)
            np.testing.assert_allclose(load_hsv(path).targets,grid.targets,rtol=0,atol=1e-12)
        with self.assertRaises(ValueError):grid.patch('ds',7,11,[[-2]],index=4)

    def test_original_lantian_file_roundtrip(self):
        path=Path('D:/Rroject_Remo_AWB/01_Param/02_Hisi/CLUT/lantian_caodi_HSV.txt')
        if not path.exists():self.skipTest('Local user sample unavailable')
        grid=load_hsv(path)
        self.assertAlmostEqual(np.asarray(grid.targets).reshape(-1,3)[:,1].max(),1.179)
        self.assertFalse(grid.preview_supported)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'out.txt';export_hsv(out,grid)
            self.assertEqual(path.read_bytes(),out.read_bytes())


@skip('V0.4.60 已删除设备表/预览来源界面；独立 HSV 导入、导出和应用见 test_v0460')
class ImportWorkflowTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def enter(self):
        p=self.panel;p.method.set('CLUT 调色');p.switch_method();self.wait_preview()
        return p.clut_editor

    def fixtures(self,folder,opaque=False):
        hsv=HSVGrid().patch('dh',0,7,[[10]],index=4)
        if opaque:
            a=list(hsv.targets);a[2]=.01;hsv=replace(hsv,targets=tuple(a))
        h=Path(folder)/'hsv.txt';export_hsv(h,hsv)
        delta=np.zeros((17,17,17,3),np.int16);delta[8,4,2]=(-2,15,-4)
        device=HSGrid(base_words=tuple(map(int,pack_deltas(delta))))
        c=Path(folder)/'device.txt';export_hisi(c,device)
        return h,c,hsv,device

    def load(self,path,hsv=False):
        with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(path)),mock.patch('isp_tool.ui.grading_workspace.messagebox.askyesno',return_value=True):
            (self.panel.load_hsv_file if hsv else self.panel.load_clut_file)()

    def test_both_import_orders_keep_both_tables_and_reveal_values(self):
        e=self.enter();p=self.panel;revision=p.revision
        with tempfile.TemporaryDirectory() as folder:
            h,c,hsv,device=self.fixtures(folder)
            for order in ((h,c),(c,h)):
                for path in order:self.load(path,path==h)
                self.assertEqual(e.state.grid.targets,hsv.targets)
                self.assertEqual(e.state.device_grid,device)
                self.assertEqual(e.shape,(25,12));self.assertEqual(e.state.preview_source,'device')
                self.assertEqual(p.revision,revision)
                self.assertEqual(e.state.selected,(0,7));self.assertEqual(e.state.slice_index,4)
                self.assertEqual(e.node_values()[0],10)
                view=e.device_view;view.mode.set('RGB 节点');view.change_mode();view.index.set('2');view.render()
                values=[tuple(view.table.item(i,'values')) for i in view.table.get_children()]
                self.assertEqual(len(values),289)
                self.assertTrue(any(row[1:7]==('8','4','2','-2','15','-4') for row in values))
                self.assertTrue(view.table.selection())
                self.assertNotEqual(int(view.table.item(view.table.selection()[0],'values')[-1]),0)
                view.mode.set('原始整数');view.change_mode();view.index.set('43');view.render()
                self.assertEqual(int(view.table.item(view.table.get_children()[-1],'values')[0]),5507)

    def test_unknown_third_field_can_use_device_preview_and_exact_export(self):
        e=self.enter();p=self.panel
        with tempfile.TemporaryDirectory() as folder:
            h,c,hsv,device=self.fixtures(folder,opaque=True)
            self.load(h,True);self.assertFalse(p.apply_clut_parameters())
            self.load(c);self.assertTrue(p.apply_clut_parameters());self.wait_preview()
            self.assertEqual(e.state.grid.targets,hsv.targets)
            self.assertEqual(e.state.applied_grid,device)
            np.testing.assert_allclose(p.preview_processor()(p.document.rgb),apply_clut(p.document.rgb,build_clut(device)))
            out=Path(folder)/'out.txt'
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(out)):p.export_clut_file()
            deadline=time.monotonic()+8
            while p.io_future is not None and time.monotonic()<deadline:self.root.update();time.sleep(.01)
            self.assertIsNone(p.io_future);np.testing.assert_array_equal(read_words(out),read_words(c))
            p.clut_preview_source.set('编辑参数（软件近似）');p.select_clut_source()
            self.assertFalse(p.apply_clut_parameters());self.assertEqual(e.state.applied_grid,device)

    def test_edit_switches_to_software_and_restore_recovers_both(self):
        e=self.enter();p=self.panel
        with tempfile.TemporaryDirectory() as folder:
            h,c,hsv,device=self.fixtures(folder)
            self.load(h,True);self.load(c);p.apply_clut_parameters();self.wait_preview()
            revision=p.revision
            e.select_node(0,7);e.variables[0].set('20');self.assertTrue(e.commit_node())
            self.assertEqual(e.state.preview_source,'editor');self.assertEqual(e.state.device_grid,device)
            self.assertEqual(e.state.applied_grid,device);self.assertEqual(p.revision,revision)
            self.assertFalse(p.clut_ready())
            p.restore_clut_applied()
            self.assertEqual(e.state.grid.targets,hsv.targets);self.assertEqual(e.state.device_grid,device)
            self.assertEqual(e.state.preview_source,'device');self.assertTrue(p.clut_ready())

    def test_invalid_import_feedback_is_atomic(self):
        e=self.enter();p=self.panel
        with tempfile.TemporaryDirectory() as folder:
            h,c,hsv,device=self.fixtures(folder)
            self.load(h,True);self.load(c)
            bad=Path(folder)/'bad.txt';bad.write_text('invalid')
            with mock.patch.object(p.clut_window,'winfo_viewable',return_value=True),mock.patch('isp_tool.ui.grading_workspace.messagebox.showerror') as popup:
                self.load(bad,True);self.load(bad)
                self.assertEqual(popup.call_count,2)
            self.assertEqual(e.state.grid.targets,hsv.targets);self.assertEqual(e.state.device_grid,device)
            self.assertIn('导入失败',p.error.get())

    def test_device_state_isolated_between_images(self):
        e=self.enter();p=self.panel;a=p.document
        with tempfile.TemporaryDirectory() as folder:
            h,c,hsv,device=self.fixtures(folder)
            self.load(h,True);self.load(c);p.apply_clut_parameters();self.wait_preview()
            p.documents.append(ColorDocument('second.png',a.rgb.copy(),None,8,'sRGB'))
            p.select_document(1);self.wait_preview();self.enter()
            self.assertIsNone(e.state.device_grid);self.assertFalse(e.device_view.table.get_children())
            self.assertEqual(e.state.grid,HSGrid())
            p.select_document(0);self.wait_preview()
            self.assertEqual(e.state.device_grid,device);self.assertEqual(e.state.grid.targets,hsv.targets)
            self.assertEqual(e.state.preview_source,'device')

    def test_device_view_reclaims_editing_space(self):
        e=self.enter();p=self.panel
        with tempfile.TemporaryDirectory() as folder:
            h,c,hsv,device=self.fixtures(folder)
            self.load(c);p.open_clut_window();p.clut_window.geometry('1000x650');self.root.update()
            self.assertTrue(e.device_view.winfo_ismapped())
            self.assertFalse(e.controls.winfo_ismapped());self.assertFalse(e.parameter_header.winfo_ismapped())
            self.assertGreater(e.device_view.table.winfo_height(),120)
            e.notebook.select(1);self.root.update()
            self.assertTrue(e.parameter_header.winfo_ismapped());self.assertTrue(e.controls.winfo_ismapped())
