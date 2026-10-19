"""CLUT editing, neutral/seam handling, persistence, packing and isolation."""
import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase,mock,skip
import numpy as np
import cv2
from PIL import Image
from isp_tool.grading.clut import (HSGrid,CLUTState,map_hsv,build_clut,apply_clut,
    save_parameters,load_parameters,export_clut,load_clut,read_json,atomic_json)
from isp_tool.grading.hisi_clut import pack_deltas,unpack_words,read_words,export_hisi,quantize_grid
from isp_tool.grading.image_io import ColorDocument,export_processed_image
from isp_tool.grading.model import ColorPoint,raster8
from tests import test_v0444


def warm_grid():
    a=np.full((24,9),15.);a[:,0]=0
    return HSGrid(tuple(a.ravel()))


class CLUTMathTests(TestCase):
    def test_identity_and_neutral_axis(self):
        rgb=np.random.default_rng(51).random((31,41,3),dtype=np.float32)
        np.testing.assert_array_equal(apply_clut(rgb,build_clut(HSGrid())),rgb)
        gray=np.repeat(np.linspace(0,1,101,dtype=np.float32)[:,None],3,axis=1).reshape(101,1,3)
        np.testing.assert_allclose(apply_clut(gray,build_clut(warm_grid())),gray,atol=1e-7)

    def test_periodic_seam_and_source_immutable(self):
        grid=HSGrid().patch('dh',0,4,[[20]])
        src=np.array([[[359.999,.5,.8],[.001,.5,.8]]],np.float32);before=src.copy()
        out=map_hsv(src,grid)
        self.assertLess(abs(float(out[0,0,0]-out[0,1,0])),.003)
        np.testing.assert_array_equal(src,before)
        np.testing.assert_array_equal(out[...,2],src[...,2])

    def test_nodes_preserve_v_and_no_nonfinite(self):
        lut=build_clut(warm_grid())
        source=np.stack(np.meshgrid(*([np.linspace(0,1,33)]*3),indexing='ij'),axis=-1)
        np.testing.assert_allclose(lut.max(axis=-1),source.max(axis=-1),atol=2e-7)
        self.assertTrue(np.all(np.isfinite(lut)))
        self.assertFalse(lut.flags.writeable)

    def test_validation_and_history(self):
        for component,value,column in [('dh',float('nan'),2),('dh',181,2),('ds',1.1,2),('dh',1,0)]:
            with self.assertRaises(ValueError):HSGrid().patch(component,0,column,[[value]])
        s=CLUTState();grid=warm_grid();self.assertTrue(s.replace(grid));self.assertFalse(s.replace(grid))
        self.assertTrue(s.travel());self.assertEqual(s.grid,HSGrid());self.assertTrue(s.travel(True));self.assertEqual(s.grid,grid)

    def test_parameter_and_lut_json_roundtrip(self):
        grid=warm_grid()
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'params.json';q=Path(directory)/'lut.json'
            save_parameters(p,grid,'source.png');restored,source=load_parameters(p)
            self.assertEqual(grid,restored);self.assertEqual(source,'source.png')
            export_clut(q,grid);np.testing.assert_array_equal(load_clut(q),build_clut(grid))
            data=read_json(p);data['units']['saturation']='percent';atomic_json(p,data)
            with self.assertRaises(ValueError):load_parameters(p)

    def test_exported_lut_and_image_agree(self):
        grid=warm_grid();rgb=np.random.default_rng(4).random((80,90,3),dtype=np.float32)
        doc=ColorDocument('source',rgb,None,8,'sRGB')
        with tempfile.TemporaryDirectory() as directory:
            lut_file=Path(directory)/'lut.json';image_file=Path(directory)/'result.png'
            export_clut(lut_file,grid)
            export_processed_image(image_file,doc,lambda a:apply_clut(a,build_clut(grid)))
            with Image.open(image_file) as image:
                np.testing.assert_array_equal(image,raster8(apply_clut(rgb,load_clut(lut_file))))


class HisiPackingTests(TestCase):
    def test_random_roundtrip_and_known_bit_order(self):
        delta=np.random.default_rng(9).integers(-511,512,(17,17,17,3))
        words=pack_deltas(delta);self.assertEqual(len(words),5508)
        np.testing.assert_array_equal(unpack_words(words),delta)
        delta[:]=0;delta[0,0,0]=(-1,2,-3);delta[1,0,0]=(4,5,6)
        words=pack_deltas(delta)
        self.assertEqual(int(words[0]),1023|(2<<10)|(1021<<20))
        self.assertEqual(int(words[1]),4|(5<<10)|(6<<20))

    def test_padding_and_range_rejected(self):
        delta=np.zeros((17,17,17,3))
        delta[0,0,0,0]=-512
        with self.assertRaises(ValueError):pack_deltas(delta)
        words=np.zeros(5508,dtype=int);words[-1]=1
        with self.assertRaises(ValueError):unpack_words(words)

    def test_txt_export_readback_quantization_and_no_wrap(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'clut.txt'
            export_hisi(path,warm_grid());words=read_words(path)
            np.testing.assert_array_equal(unpack_words(words),quantize_grid(warm_grid()))
            self.assertEqual(len(path.read_text().splitlines()),612)
            prior=path.read_bytes()
            huge=np.full((24,9),180.);huge[:,0]=0
            with self.assertRaises(ValueError):export_hisi(path,HSGrid(tuple(huge.ravel())))
            self.assertEqual(path.read_bytes(),prior)


@skip('V0.4.60 已移除旧 24×9 HS/设备 CLUT 界面；现行 HSV 工作流见 test_v0457/test_v0460')
class CLUTWorkspaceTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def use_clut(self):
        self.panel.method.set('CLUT 调色');self.panel.switch_method();self.wait_preview()
        return self.panel.clut_editor

    def test_mode_exclusive_and_preserves_points(self):
        p=self.panel;p.selected=0;p.edit([ColorPoint((.8,.2,.1),(.4,.4,.3))]);self.wait_preview()
        old=p.output.copy();points=copy.deepcopy(p.history.points)
        self.use_clut();np.testing.assert_array_equal(p.source,p.output)
        p.clut_changed(warm_grid(),True);p.apply_clut_parameters();self.wait_preview()
        np.testing.assert_array_equal(p.output,apply_clut(p.source,build_clut(warm_grid())))
        p.method.set('取色调色');p.switch_method();self.wait_preview()
        np.testing.assert_array_equal(p.output,old);self.assertEqual(points,p.history.points)

    def test_input_intermediate_commit_dedupe_and_undo(self):
        p=self.panel;e=self.use_clut();revision=p.revision
        e.variables[0].set('-');self.assertEqual(p.revision,revision)
        self.assertFalse(e.commit_node());self.assertEqual(p.revision,revision)
        e.variables[0].set('12.5');self.assertTrue(e.commit_node());self.wait_preview()
        count=len(e.state.undo_stack);revision=p.revision;e.commit_node()
        self.assertEqual(p.revision,revision);self.assertEqual(len(e.state.undo_stack),count)
        e.travel(False);self.wait_preview();self.assertEqual(e.state.grid,HSGrid())
        e.travel(True);self.wait_preview();self.assertEqual(e.state.grid.dh[4],12.5)

    def test_two_images_drafts_and_late_focusout_isolation(self):
        p=self.panel;e=self.use_clut();a=p.document
        p.clut_changed(warm_grid(),True);p.apply_clut_parameters();self.wait_preview();old=p.output.copy()
        e.variables[0].set('-');widget=SimpleNamespace();e.mark_focus(widget)
        b=ColorDocument('b.png',a.rgb.copy(),None,8,'sRGB');p.documents.append(b)
        p.select_document(1);self.wait_preview();self.use_clut()
        with mock.patch.object(e,'winfo_ismapped',return_value=True):e.focus_commit(widget)
        self.assertEqual(e.state.grid,HSGrid());np.testing.assert_array_equal(p.source,p.output)
        p.select_document(0);self.wait_preview();self.assertEqual(e.variables[0].get(),'-')
        np.testing.assert_array_equal(p.output,old)

    def test_table_atomic_paste_selection_reset(self):
        e=self.use_clut();p=self.panel;e.select_node(2,2)
        e.paste_cells('dh','1\t2\n3\t4');self.wait_preview()
        self.assertEqual(e.state.grid.dh[2*9+2],1);before=e.state.grid
        e.paste_cells('dh','1\t999\n3\t4');self.assertEqual(e.state.grid,before)
        e.select_node(3,3,True);e.reset_selected();self.wait_preview()
        self.assertEqual(e.state.grid,HSGrid())

    def test_slice_and_tabs_do_not_reprocess(self):
        e=self.use_clut();p=self.panel;revision=p.revision;grid=e.state.grid
        e.value.set('.5');e.change_slice();e.notebook.select(1);self.root.update()
        self.assertEqual(e.state.grid,grid);self.assertEqual(p.revision,revision)

    def test_wheel_drag_single_history_step_and_no_image_pan(self):
        p=self.panel;e=self.use_clut();x,y=e.point_xy(0,4,e.state.grid)
        e.wheel_press(SimpleNamespace(x=x,y=y))
        for dy in (10,15,20):e.wheel_drag(SimpleNamespace(x=x,y=y-dy))
        self.assertFalse(e.state.undo_stack)
        e.wheel_release();self.wait_preview();self.assertEqual(len(e.state.undo_stack),1)
        p.press(SimpleNamespace(x=10,y=10));self.assertIsNone(p.drag)
        e.travel(False);self.wait_preview();self.assertEqual(e.state.grid,HSGrid())

    def test_export_blocks_draft_and_snapshots_clut_processor(self):
        p=self.panel;e=self.use_clut();e.variables[0].set('-')
        with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename') as dialog:
            p.export();p.export_clut_file();dialog.assert_not_called()
        e.reset_selected();p.clut_changed(warm_grid(),True);p.apply_clut_parameters();self.wait_preview()
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'out.png')
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=path):p.export()
            p.io_future.result(timeout=5)
            with Image.open(path) as image:np.testing.assert_array_equal(image,raster8(apply_clut(p.document.rgb,build_clut(warm_grid()))))

    def test_parameter_load_is_explicit_and_undoable(self):
        p=self.panel;e=self.use_clut()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'params.json';save_parameters(path,warm_grid(),'different.png')
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(path)),mock.patch('isp_tool.ui.grading_workspace.messagebox.askyesno',return_value=False):p.load_clut_parameters()
            self.assertEqual(e.state.grid,HSGrid())
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(path)),mock.patch('isp_tool.ui.grading_workspace.messagebox.askyesno',return_value=True):p.load_clut_parameters()
            self.wait_preview();self.assertEqual(e.state.grid,warm_grid())
            e.travel(False);self.wait_preview();self.assertEqual(e.state.grid,HSGrid())

    def test_compact_display_does_not_quantize_unedited_fields(self):
        p=self.panel;e=self.use_clut()
        grid=HSGrid().patch('dh',0,4,[[12.123456789]]).patch('ds',0,4,[[.0123456789]])
        p.clut_changed(grid,True);self.wait_preview();revision=p.revision
        self.assertEqual(e.variables[0].get(),'12.1')
        e.commit_node();self.assertEqual(p.revision,revision);self.assertEqual(e.state.grid,grid)
        e.variables[0].set('13');e.commit_node();self.wait_preview()
        self.assertEqual(e.state.grid.ds[4],grid.ds[4])

    def test_clut_panel_width_tracks_visible_editor(self):
        p=self.panel;e=self.use_clut()
        self.root.update_idletasks()
        p.editor_host.event_generate('<Configure>');self.root.update_idletasks()
        self.assertGreaterEqual(int(p.parameter_canvas.cget('width')),p.clut_panel.winfo_reqwidth())
        self.assertGreaterEqual(e.canvas_height,280)

    def test_rapid_clut_changes_keep_latest_request(self):
        p=self.panel;self.use_clut()
        for value in (1,2,5,9,20):p.clut_changed(HSGrid().patch('dh',0,4,[[value]]),False)
        grid=HSGrid().patch('dh',0,4,[[25]])
        p.clut_changed(grid,True);p.apply_clut_parameters();self.wait_preview()
        self.assertIsNone(p.future);self.assertEqual(p._shown_revision,p.revision)
        np.testing.assert_array_equal(p.output,apply_clut(p.source,build_clut(grid)))

    def test_bypass_export_processor_is_identity(self):
        p=self.panel;self.use_clut();p.clut_changed(warm_grid(),True);self.wait_preview()
        p.enabled.set(False);p.toggle_enabled()
        np.testing.assert_array_equal(p.preview_processor()(p.document.rgb),p.document.rgb)

    def test_selecting_wheel_node_does_not_reprocess(self):
        p=self.panel;e=self.use_clut();revision=p.revision
        x,y=e.point_xy(6,6,e.state.grid)
        e.wheel_press(SimpleNamespace(x=x,y=y));e.wheel_release()
        self.assertEqual(e.state.selected,(6,6));self.assertEqual(p.revision,revision)
