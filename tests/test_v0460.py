"""HSV-only workflow, surgical text persistence and honest image preview."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock
import re
import tempfile
import time
import numpy as np
from PIL import Image
from isp_tool.grading.hsv_grid import HSVGrid, HSVState, SHAPE, load_hsv, export_hsv
from isp_tool.grading.clut import build_clut, apply_clut
from isp_tool.grading.image_io import ColorDocument, export_processed_image
from isp_tool.grading.model import raster8
from tests import test_v0444

SAMPLE=Path('D:/Rroject_Remo_AWB/01_Param/02_Hisi/CLUT/26_9_28_lantian_caodi_HSV.txt')


class HSVPersistenceTests(TestCase):
    def test_all_available_real_files_byte_exact(self):
        files=[SAMPLE,SAMPLE.with_name('lantian_caodi_HSV.txt')]
        files += [Path('C:/Users/remo/Downloads')/n for n in ('74HS.txt','10HSV.txt','222HSV.txt','lantian_caodi_HSV.txt')]
        files=[p for p in files if p.exists()]
        if not files:self.skipTest('User fixtures unavailable')
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'out.txt'
            for path in files:
                with self.subTest(path=path):
                    export_hsv(out,load_hsv(path))
                    self.assertEqual(out.read_bytes(),path.read_bytes())

    def test_edit_patches_only_one_token_keeps_bom_order_and_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'in.txt';out=Path(folder)/'out.txt'
            a=np.array(HSVGrid().targets).reshape(*SHAPE,3)
            a[4,7,6]=[106.12345678901234,.6571234567890123,.1234567890123456]
            grid=replace(HSVGrid(),targets=tuple(a.ravel()),prefix='0,0,0,0,0,0,1,2,3,4\n')
            export_hsv(path,grid)
            lines=path.read_text().splitlines();records=[s for s in lines if s.startswith('{')]
            header=[s for s in lines if not s.startswith('{')]
            text='\ufeff'+'\r\n'.join(header+list(reversed(records)))+'\r\n'
            path.write_bytes(text.encode('utf-8'))
            loaded=load_hsv(path);export_hsv(out,loaded)
            self.assertEqual(out.read_bytes(),path.read_bytes())
            plane=loaded.plane(4);k=7*12+6
            edited=loaded.edit(4,7,6,8.987654321012345,plane.ds[k])
            export_hsv(out,edited)
            old_lines=text.splitlines(keepends=True);new_lines=out.read_bytes().decode('utf-8').splitlines(keepends=True)
            different=[(x,y) for x,y in zip(old_lines,new_lines) if x!=y]
            self.assertEqual(len(different),1)
            x,y=different[0];self.assertEqual(x.split(',')[:3],y.split(',')[:3])
            self.assertEqual(x.split(',')[4:],y.split(',')[4:])
            self.assertEqual(out.read_bytes()[:3],b'\xef\xbb\xbf')
            self.assertEqual(load_hsv(out).targets,edited.targets)
            reset=edited.reset()
            np.testing.assert_array_equal(np.array(reset.targets).reshape(-1,3)[:,2],a.reshape(-1,3)[:,2])

    def test_display_rounding_and_unchanged_components_do_not_quantize(self):
        grid=HSVGrid().patch('dh',5,6,[[1.123456789012345]],4).patch('ds',5,6,[[.01234567890123456]],4)
        p=grid.plane(4);k=5*12+6
        self.assertEqual(grid.edit(4,5,6,p.dh[k],p.ds[k]).targets,grid.targets)
        edited=grid.edit(4,5,6,2,p.ds[k])
        self.assertEqual(np.asarray(edited.targets).reshape(*SHAPE,3)[4,5,6,1],np.asarray(grid.targets).reshape(*SHAPE,3)[4,5,6,1])

    def test_unknown_invalid_input_never_overwrites_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'in.txt';export_hsv(path,HSVGrid())
            original=path.read_bytes()
            path.write_text(path.read_text().replace('{ 0,  0,  0,','{ 1,  0,  0,',1))
            with self.assertRaises(ValueError):load_hsv(path)
            self.assertNotEqual(path.read_bytes(),original)
            out=Path(folder)/'keep.txt';out.write_text('keep')
            with self.assertRaises(ValueError):export_hsv(out,object())
            self.assertEqual(out.read_text(),'keep')


class HSVOnlyWorkspaceTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def enter(self):
        p=self.panel;p.method.set('HSV 调色');p.switch_method();self.wait_preview()
        return p.clut_editor

    def load(self,path):
        with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(path)),mock.patch('isp_tool.ui.grading_workspace.messagebox.askyesno',return_value=True):
            self.panel.load_hsv_file()

    def test_only_hsv_entries_and_default_state(self):
        e=self.enter();p=self.panel
        self.assertIsInstance(e.state,HSVState);self.assertIsInstance(e.state.grid,HSVGrid)
        self.assertEqual([e.notebook.tab(t,'text') for t in e.notebook.tabs()],['色轮','Delta Hue','Delta Sat'])
        self.assertFalse(hasattr(p,'load_clut_file'));self.assertFalse(hasattr(p,'export_clut_file'))
        self.assertFalse(hasattr(p,'load_clut_parameters'));self.assertFalse(hasattr(p,'clut_preview_source'))
        self.assertEqual(p.export_menu.entrycget(1,'label'),'导出 HSV TXT…')
        self.assertEqual(p.mode.get(),'滑动对比')
        def texts(widget):
            values=[]
            if 'text' in widget.keys():values.append(str(widget.cget('text')))
            for child in widget.winfo_children():values+=texts(child)
            return values
        self.assertFalse(any('JSON' in t or '设备数据' in t for t in texts(p)))
        self.assertTrue(any('CLUT 生效强度' in t for t in texts(p)))

    def test_import_sync_target_colors_wheel_and_layer(self):
        e=self.enter();p=self.panel;revision=p.revision
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'hsv.txt'
            grid=HSVGrid().patch('dh',4,3,[[25]],4).patch('ds',4,3,[[.2]],4)
            export_hsv(path,grid);self.load(path)
            self.assertEqual(e.state.selected,(4,3));self.assertEqual(e.state.slice_index,4)
            self.assertEqual(p.revision,revision);self.assertEqual(e.node_values(),(25,.2))
            target=e.color(85,.519,.5);original=e.color(60,.319,.5)
            for canvas in e.tables.values():
                self.assertEqual(canvas.itemcget(f'target-cell-4-3','fill'),target)
                self.assertEqual(canvas.itemcget('original-cell-4-3','fill'),original)
            self.assertEqual(e.wheel.itemcget('target-node-4-3','fill'),target)
            self.assertNotEqual(e.point_xy(4,3,grid),e.point_xy(4,3,HSVGrid()))
            e.value.set('.75');e.change_slice()
            self.assertEqual(e.state.slice_index,4)
            self.assertEqual(e.node_values(),(grid.plane(4).dh[4*12+3],grid.plane(4).ds[4*12+3]))

    def test_export_commits_draft_without_applying_and_restore(self):
        e=self.enter();p=self.panel;revision=p.revision
        e.select_node(4,3);e.variables[0].set('8.1256789012345')
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'hsv.txt'
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(out)):
                p.export_parameter_txt()
            self.assertEqual(load_hsv(out).targets,e.state.grid.targets)
            self.assertEqual(p.revision,revision);self.assertEqual(e.state.applied_grid,HSVGrid())
            self.assertTrue(e.state.pending())
            p.restore_clut_applied();self.assertEqual(e.state.grid,HSVGrid());self.assertFalse(e.state.pending())

    def test_inline_navigation_commits_without_enter(self):
        e=self.enter();e.select_node(4,3);e.open_inline('dh','12.5')
        event=SimpleNamespace(x=int(5.5*e.cw-e.tables['dh'].canvasx(0)),y=int(5.5*e.ch-e.tables['dh'].canvasy(0)),state=0)
        e.table_press(event,'dh')
        self.assertEqual(e.state.grid.plane(4).dh[4*12+3],12.5)
        self.assertTrue(e.state.pending());self.assertEqual(e.state.applied_grid,HSVGrid())

    def test_unknown_apply_error_is_visible_and_data_still_exportable(self):
        e=self.enter();p=self.panel;a=list(HSVGrid().targets);a[2]=.01
        p.clut_changed(replace(HSVGrid(),targets=tuple(a)),True)
        with mock.patch.object(p.clut_window,'winfo_viewable',return_value=True),mock.patch('isp_tool.ui.grading_workspace.messagebox.showerror') as popup:
            self.assertFalse(p.apply_clut_parameters());popup.assert_called_once()
        self.assertEqual(p.clut_status.get(),'未应用');self.assertEqual(e.state.applied_grid,HSVGrid())
        e.reset_all();self.assertEqual(e.state.grid.targets[2],.01)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'out.txt'
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(path)):p.save_hsv_file()
            self.assertEqual(load_hsv(path).targets[2],.01)

    def test_applied_preview_image_export_and_image_isolation(self):
        e=self.enter();p=self.panel
        a=np.array(HSVGrid().targets).reshape(*SHAPE,3);a[:,:,1:,0]+=15
        p.clut_changed(replace(HSVGrid(),targets=tuple(a.ravel())),True)
        self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        expected=apply_clut(p.document.rgb,build_clut(e.state.applied_grid))
        self.assertGreater(float(np.max(abs(expected-p.document.rgb))),.01)
        np.testing.assert_allclose(p.preview_processor()(p.document.rgb),expected)
        np.testing.assert_allclose(p.output,expected,atol=1e-6)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'image.png'
            export_processed_image(out,p.document,p.preview_processor())
            np.testing.assert_array_equal(np.asarray(Image.open(out)),raster8(expected))
        original=e.state.grid
        p.documents.append(ColorDocument('second.png',p.document.rgb.copy(),None,8,'sRGB'))
        p.select_document(1);self.wait_preview();self.enter()
        self.assertEqual(e.state.grid,HSVGrid())
        p.select_document(0);self.wait_preview();self.assertEqual(e.state.grid,original)

    def test_invalid_import_is_atomic_and_minimum_window_controls_fit(self):
        e=self.enter();p=self.panel
        p.open_clut_window();p.clut_window.geometry('900x650');self.root.update()
        before=e.state.grid
        with tempfile.TemporaryDirectory() as folder:
            bad=Path(folder)/'bad.txt';bad.write_text('0,0,0,')
            with mock.patch('isp_tool.ui.grading_workspace.messagebox.showerror') as popup:self.load(bad)
            popup.assert_called_once();self.assertEqual(e.state.grid,before)
        self.assertTrue(e.controls.winfo_ismapped());self.assertGreater(e.notebook.winfo_height(),150)
        e.side_view.yview_moveto(1);self.root.update()
        bottom=p.hsv_footer.winfo_rooty()+p.hsv_footer.winfo_height()
        self.assertLessEqual(bottom,p.clut_window.winfo_rooty()+p.clut_window.winfo_height())

    def test_neighborhood_drag_undo_and_apply_deduplication(self):
        e=self.enter();p=self.panel;revision=p.revision
        e.state.radius=2;e.select_node(4,5)
        e.variables[0].set('12');self.assertTrue(e.commit_node())
        grid=e.state.grid;planes=np.array(grid.targets).reshape(*SHAPE,3)
        initial=np.array(HSVGrid().targets).reshape(*SHAPE,3)
        changed=np.any(planes!=initial,axis=-1)
        self.assertGreater(changed[4].sum(),1)
        self.assertEqual(changed.sum(),9*changed[4].sum())
        np.testing.assert_array_equal(planes[:,:,0],initial[:,:,0])
        e.travel(False);self.assertEqual(e.state.grid,HSVGrid())
        e.travel(True);self.assertEqual(e.state.grid,grid)
        e.state.radius=0;xy=e.point_xy(4,5,e.state.grid);history=len(e.state.undo_stack)
        e.wheel_press(SimpleNamespace(x=xy[0],y=xy[1]))
        e.wheel_drag(SimpleNamespace(x=xy[0]+9,y=xy[1]+5))
        self.assertEqual(p.revision,revision);self.assertEqual(e.state.grid,grid)
        e.wheel_release();self.assertEqual(len(e.state.undo_stack),history+1)
        self.assertEqual(p.revision,revision)
        self.assertTrue(p.apply_clut_parameters());self.wait_preview();revision=p.revision
        self.assertTrue(p.apply_clut_parameters());self.assertEqual(p.revision,revision)

    def test_pick_overlay_uses_original_and_never_changes_processing(self):
        e=self.enter();p=self.panel
        with mock.patch.object(p,'open_clut_window'):self.assertTrue(p.pick_clut_at(20,20))
        from isp_tool.grading.hsv_grid import locate
        vi,r,c=locate(p.document.rgb[20,20])
        self.assertEqual(e.state.slice_index,4);self.assertEqual(e.state.selected,(r,c))
        self.assertEqual(e.state.tab,'Delta Hue')
        expected=p.preview_processor()(p.document.rgb)
        e.influence.set(True);e.inspect_changed()
        np.testing.assert_array_equal(p.preview_processor()(p.document.rgb),expected)
        self.assertFalse(e.state.pending())
