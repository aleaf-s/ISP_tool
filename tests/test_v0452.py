"""Resizable CLUT window and strictly explicit application."""
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock, skip
import numpy as np
from isp_tool.grading.clut import HSGrid,apply_clut,build_clut,save_parameters,load_parameters
from isp_tool.grading.image_io import ColorDocument
from tests import test_v0444
from tests import test_v0442
from isp_tool.models import ParameterSpec
from isp_tool.ui.number_format import format_number
from isp_tool.ui.widgets.parameter_control import ParameterControl
from isp_tool.ui.widgets.ccm_matrix_editor import CCMMatrixEditor,FLOAT,FIXED
from isp_tool.grading.model import ColorPoint


@skip('V0.4.60 已移除旧 HS/JSON 界面；HSV 显式应用、恢复和窗口回归见 test_v0457/test_v0460')
class CLUTApplyTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def editor(self):
        p=self.panel;p.method.set('CLUT 调色');p.switch_method();self.wait_preview()
        return p.clut_editor

    def test_numeric_enter_only_edits_draft_apply_is_deduplicated(self):
        p=self.panel;e=self.editor();before=p.output.copy();revision=p.revision
        e.variables[0].set('45');e.commit_node()
        self.assertEqual(p.revision,revision);np.testing.assert_array_equal(p.output,before)
        self.assertEqual(p.clut_status.get(),'待应用')
        self.assertEqual(e.state.applied_grid,HSGrid())
        self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        self.assertEqual(p.revision,revision+1)
        np.testing.assert_array_equal(p.output,apply_clut(p.source,build_clut(e.state.grid)))
        p.apply_clut_parameters();self.assertEqual(p.revision,revision+1)
        self.assertEqual(p.clut_status.get(),'已应用')

    def test_drag_reset_and_undo_do_not_process_image(self):
        p=self.panel;e=self.editor();revision=p.revision
        x,y=e.point_xy(0,4,e.state.grid);e.wheel_press(SimpleNamespace(x=x,y=y))
        e.wheel_drag(SimpleNamespace(x=x,y=y-20));e.wheel_release()
        dragged=e.state.grid
        self.assertNotEqual(dragged,HSGrid());self.assertEqual(p.revision,revision)
        p.apply_clut_parameters();self.wait_preview();output=p.output.copy();revision=p.revision
        e.reset_all();self.assertEqual(p.revision,revision)
        np.testing.assert_array_equal(p.output,output)
        e.travel(False);self.assertEqual(e.state.grid,dragged)
        e.travel(True);self.assertEqual(e.state.grid,HSGrid())
        self.assertEqual(e.state.applied_grid,dragged);self.assertEqual(p.revision,revision)

    def test_apply_validates_all_nodes_atomically(self):
        p=self.panel;e=self.editor();revision=p.revision
        e.variables[0].set('10');e.select_node(1,4);e.variables[1].set('-')
        self.assertFalse(p.apply_clut_parameters())
        self.assertEqual(e.state.grid,HSGrid());self.assertEqual(e.state.applied_grid,HSGrid())
        self.assertEqual(len(e.state.drafts),2);self.assertEqual(p.revision,revision)
        e.variables[1].set('.1');self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        self.assertEqual(e.state.applied_grid.dh[4],10)
        self.assertEqual(e.state.applied_grid.ds[13],.1)
        self.assertFalse(e.state.drafts)

    def test_load_save_draft_and_export_require_apply(self):
        p=self.panel;e=self.editor();revision=p.revision
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'params.json';grid=HSGrid().patch('dh',0,4,[[20]])
            save_parameters(path,grid,p.document.path)
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(path)):
                p.load_clut_parameters()
            self.assertEqual(e.state.grid,grid);self.assertEqual(e.state.applied_grid,HSGrid())
            self.assertEqual(p.revision,revision)
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename') as dialog:
                p.export();p.export_clut_file();dialog.assert_not_called()
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(path)):
                p.save_clut_parameters()
            self.assertEqual(load_parameters(path)[0],grid)
            self.assertEqual(e.state.applied_grid,HSGrid())
            p.apply_clut_parameters();self.wait_preview();self.assertTrue(p.clut_ready())

    def test_each_image_keeps_separate_applied_and_draft_grids(self):
        p=self.panel;e=self.editor();a=p.document
        applied=HSGrid().patch('dh',0,4,[[20]]);draft=HSGrid().patch('dh',0,4,[[40]])
        p.clut_changed(applied,True);p.apply_clut_parameters();self.wait_preview()
        p.clut_changed(draft,True)
        p.documents.append(ColorDocument('second.png',a.rgb.copy(),None,8,'sRGB'))
        p.select_document(1);self.wait_preview();self.editor()
        self.assertEqual(e.state.applied_grid,HSGrid());self.assertEqual(e.state.grid,HSGrid())
        p.select_document(0);self.wait_preview()
        self.assertEqual(e.state.grid,draft);self.assertEqual(e.state.applied_grid,applied)
        np.testing.assert_array_equal(p.output,apply_clut(p.source,build_clut(applied)))

    def test_window_reopen_preserves_text_and_never_applies(self):
        p=self.panel;e=self.editor();revision=p.revision
        p.open_clut_window();self.root.update_idletasks()
        e.variables[0].set('-');p.hide_clut_window()
        self.assertEqual(p.clut_window.state(),'withdrawn')
        p.open_clut_window();self.root.update_idletasks()
        self.assertEqual(e.variables[0].get(),'-');self.assertEqual(p.revision,revision)
        self.assertEqual(tuple(map(int,p.clut_window.resizable())),(1,1))

    def test_window_resize_expands_wheel_and_table(self):
        p=self.panel;e=self.editor();self.root.deiconify();self.root.update()
        p.open_clut_window();self.root.update()
        def resize(height):
            p.clut_window.geometry(f'1000x{height}')
            for _ in range(5):self.root.update();time.sleep(.02)
        small=p.clut_window.minsize()[1]
        large=min(small+250,p.clut_window.maxsize()[1])
        resize(small)
        radius=e.wheel_geometry()[2]
        resize(large)
        self.assertGreater(e.wheel_geometry()[2],radius)
        e.notebook.select(1);self.root.update()
        resize(small)
        canvas=e.tables['dh'];old=canvas.winfo_height()
        resize(large)
        self.assertGreater(canvas.winfo_height(),old)

    def test_switch_during_drag_cannot_write_into_other_image(self):
        p=self.panel;e=self.editor();a=p.document
        p.documents.append(ColorDocument('second.png',a.rgb.copy(),None,8,'sRGB'))
        x,y=e.point_xy(0,4,e.state.grid);e.wheel_press(SimpleNamespace(x=x,y=y))
        e.wheel_drag(SimpleNamespace(x=x,y=y-20))
        p.select_document(1);self.wait_preview();self.editor()
        self.assertEqual(e.state.grid,HSGrid());self.assertEqual(e.state.applied_grid,HSGrid())
        self.assertNotEqual(p.state_for(a).clut.grid,HSGrid())
        self.assertEqual(p.state_for(a).clut.applied_grid,HSGrid())

    def test_mode_switch_hides_window_and_preserves_applied_snapshot(self):
        p=self.panel;e=self.editor();p.open_clut_window()
        e.variables[0].set('20');p.apply_clut_parameters();self.wait_preview()
        applied=e.state.applied_grid;e.variables[0].set('40');e.commit_node()
        p.method.set('取色调色');p.switch_method();self.wait_preview()
        self.assertEqual(p.clut_window.state(),'withdrawn')
        self.editor();self.assertEqual(e.state.applied_grid,applied)
        self.assertEqual(e.state.grid.dh[4],40)
        np.testing.assert_array_equal(p.output,apply_clut(p.source,build_clut(applied)))

    def test_grading_other_channels_keep_precision_when_one_is_edited(self):
        p=self.panel;p.selected=0
        target=(.123456789,.234567891,.345678912)
        p.edit([ColorPoint((.8,.2,.1),target,radius=25.123456,strength=.9123456)])
        self.wait_preview();revision=p.revision
        p.commit_target('RGB');p.commit_target('HSV');p.commit_influence()
        self.assertEqual(p.revision,revision)
        p.values['RGB'][0].set('100');p.commit_target('RGB');self.wait_preview()
        self.assertEqual(p.history.points[0].target[1:],target[1:])
        self.assertEqual(p.history.points[0].radius,25.123456)


class CompactNumberTests(TestCase):
    setUp=test_v0442.EditorTests.setUp
    tearDown=test_v0442.EditorTests.tearDown

    def test_step_precision_and_small_nonzero(self):
        for value,step,expected in [(1.234567,.01,'1.23'),(.123456,.001,'0.123'),
                                    (1.234567,.25,'1.23'),(64.,1,'64')]:
            self.assertEqual(format_number(value,step=step),expected)
        self.assertEqual(format_number(1.,4),'1')
        self.assertNotEqual(float(format_number(1e-8,4)),0)

    def test_parameter_focusout_and_steps_preserve_precise_model(self):
        calls=[];value=1.234567891
        c=ParameterControl(self.root,ParameterSpec('gain','Gain','float',1,0,8,.01),value,calls.append)
        self.assertEqual(c.entry_var.get(),'1.23')
        c._entry_commit();c._entry_commit();self.assertEqual(c.value(),value);self.assertFalse(calls)
        c._key_step(SimpleNamespace(state=0),1)
        self.assertAlmostEqual(c.value(),value+.01,places=12);self.assertEqual(calls,[True])
        c.entry_var.set('2.123456789');c._entry_commit();c._entry_commit()
        self.assertEqual(c.value(),2.123456789);self.assertEqual(c.entry_var.get(),'2.12')
        self.assertEqual(len(calls),2)

    def test_compact_ccm_display_never_changes_matrix(self):
        matrix=np.eye(3)*1.123456789
        e=CCMMatrixEditor(self.root,matrix)
        self.assertEqual(e.variables[0].get(),'1.1235')
        np.testing.assert_array_equal(e.matrix(),matrix)
        e.set_mode(FIXED);e.set_mode(FLOAT)
        self.assertEqual(e.variables[0].get(),'1.1235')
        np.testing.assert_array_equal(e.matrix(),matrix)
