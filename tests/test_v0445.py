"""Unified navigation; V0.4.49 keeps a shared catalogue, not shared mappings."""
import copy
import tempfile
from pathlib import Path
from concurrent.futures import Future
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock
import numpy as np
from isp_tool.grading.image_io import ColorDocument
from isp_tool.grading.model import ColorPoint, apply_lut, build_lut
from tests import test_v0444 as previous


class SharedGradingTests(unittest.TestCase):
    setUp = previous.WorkspaceTests.setUp
    tearDown = previous.WorkspaceTests.tearDown
    wait_preview = previous.WorkspaceTests.wait_preview

    def add_document(self, name='B.png', color=(.2,.3,.7)):
        self.panel.documents.append(ColorDocument(name, np.full((48,60,3),color,np.float32),None,8,'sRGB'))

    def pick(self):
        p=self.panel
        p.zoom=1;p.offset=[0,0];p.fit=False;p.pick.set(True)
        with mock.patch.object(p.canvas,'winfo_width',return_value=160):
            p.press(SimpleNamespace(x=10,y=10))

    def test_shared_points_original_pick_and_image_view_state(self):
        p=self.panel
        self.pick()
        p.values['RGB'][0].set('120');p.commit_target('RGB')
        original=copy.deepcopy(p.history.points[0])
        p.zoom=3;p.offset=[-24,-18];p.fit=False;p.divider=.3
        self.add_document()
        p.select_document(1);self.wait_preview()
        self.assertEqual(p.history.points,[])
        np.testing.assert_array_equal(p.output,p.source)
        np.testing.assert_allclose(p.output,apply_lut(p.source,build_lut(p.history.points)))
        self.pick()
        self.assertEqual(len(p.history.points),1)
        self.assertEqual(len(p.point_list.get_children()),2)
        self.assertEqual(p.history.points[0].origin,'B.png')
        np.testing.assert_allclose(p.history.points[0].source,(.2,.3,.7),atol=1e-6)
        p.values['HSV'][1].set('.8');p.commit_target('HSV')
        p.select_document(0);self.wait_preview()
        self.assertEqual(p.zoom,3)
        # Navigation retains scale, but no longer restores drag-to-pan offsets.
        width=max(1,p.canvas.winfo_width())
        if p.mode.get()=='左右并排':width=max(1,width//2)
        self.assertEqual(p.offset,[(width-p.source.shape[1]*3)/2,
                                  (max(1,p.canvas.winfo_height())-p.source.shape[0]*3)/2])
        self.assertEqual(p.divider,.3);self.assertFalse(p.fit)
        self.assertEqual(len(p.history.points),1)
        self.assertEqual(p.history.points[0],original)
        np.testing.assert_allclose(p.output,apply_lut(p.source,build_lut(p.history.points)))

    def test_remove_source_and_reimport_keep_history_and_bypass(self):
        p=self.panel;self.pick()
        p.enabled.set(False)
        points=copy.deepcopy(p.history.points)
        p.remove_document()
        self.assertEqual(p.history.points,[])
        p.travel(False);self.assertEqual(p.history.points,[])
        p.travel(True);self.assertEqual(p.history.points,[])
        self.add_document();p.select_document(0);self.wait_preview()
        self.assertTrue(p.enabled.get())
        self.assertEqual(p.history.points,[])

    def test_reset_all_requires_explicit_shared_scope_and_can_undo(self):
        p=self.panel;self.pick();self.add_document()
        with mock.patch('isp_tool.ui.grading_workspace.messagebox.askyesno',return_value=False):
            p.reset_all()
        self.assertEqual(len(p.history.points),1)
        with mock.patch('isp_tool.ui.grading_workspace.messagebox.askyesno',return_value=True) as confirm:
            p.reset_all()
            self.assertIn('当前图像',confirm.call_args.args[1])
        self.assertEqual(p.history.points,[])
        p.travel(False);self.assertEqual(len(p.history.points),1)

    def test_switch_preserves_invalid_edit_draft_without_applying(self):
        p=self.panel;self.pick();self.wait_preview();self.add_document()
        snapshot=copy.deepcopy(p.history.points)
        p.values['RGB'][0].set('-')
        p.select_document(1)
        self.assertEqual(p.values['RGB'][0].get(),'0')
        self.assertEqual(p.history.points,[])
        p.select_document(0);self.wait_preview()
        self.assertEqual(p.values['RGB'][0].get(),'-')
        self.assertEqual(p.history.points,snapshot)

    def test_latest_request_discards_previous_image_and_is_lazy(self):
        p=self.panel;self.add_document()
        future=Future();p.future=future
        old_revision=p.revision
        with mock.patch.object(p.executor,'submit',wraps=p.executor.submit) as submit:
            p.select_document(1)
            p.selected=0
            p.edit([ColorPoint((.2,.3,.7),(.3,.4,.5))])
            submit.assert_not_called()
            future.set_result((old_revision,p.documents[0].document_id,(),np.zeros((64,80,3),np.float32)))
            p.poll_preview()
            self.assertEqual(submit.call_count,1)
            self.wait_preview()
            self.assertEqual(submit.call_count,1)
        self.assertEqual(p._shown_revision,p.revision)
        self.assertEqual(p.output.shape,(48,60,3))
        np.testing.assert_allclose(p.output,apply_lut(p.source,build_lut(p.history.points)))

    def test_export_takes_current_image_with_common_mapping(self):
        p=self.panel;self.pick()
        p.values['RGB'][0].set('100');p.commit_target('RGB')
        self.add_document();p.select_document(1);self.wait_preview()
        with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value='unused.png'), \
             mock.patch('isp_tool.ui.grading_workspace.export_color_image') as export:
            p.export();p.io_future.result(timeout=5)
            self.assertIs(export.call_args.args[1],p.documents[1])
            np.testing.assert_array_equal(export.call_args.args[2],build_lut(p.history.points))
            p.io_future=None


class ToolNavigationTests(unittest.TestCase):
    def test_raw_yuv_roundtrip_preserves_numeric_draft_module_and_view(self):
        from isp_tool.ui.app import ISPApplication
        from isp_tool.yuv import YUVMetadata
        from isp_tool.models import CalibrationSession
        from isp_tool.workspace import ImageWorkItem, snapshot_for_image
        root=tk.Tk();root.withdraw();app=ISPApplication(root)
        try:
            app.selected_module_index=2
            app._build_parameter_editor(app.pipeline.modules[2])
            key=next(iter(app.parameter_controls))
            app.parameter_controls[key].entry_var.set('-')
            app.zoom=2.5;app.fit_mode=False;app.canvas_origin=(-31,42)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'tiny.yuv'
                path.write_bytes(bytes([80]*8+[128]*4))
                loaded=app._read_work_items([str(path)],None,app.pipeline.snapshot(),YUVMetadata(4,2,'NV12'),1500)[0][0].loaded
                app.work_items.append(ImageWorkItem(loaded,snapshot_for_image(app.pipeline.snapshot(),loaded),CalibrationSession(raw_metadata=loaded.metadata)))
                app._switch_workspace('yuv')
                self.assertEqual(app.tool_var.get(),'yuv')
                with mock.patch.object(app,'open_yuv_files') as import_yuv:
                    app.open_files();import_yuv.assert_called_once()
                app.yuv_frame_spin.set('-')
                app.zoom=4;app.fit_mode=False;app.canvas_origin=(13,-12)
                app._switch_workspace('isp')
                with mock.patch.object(app,'open_isp_files') as import_isp:
                    app.open_files();import_isp.assert_called_once()
                self.assertEqual(app.selected_module_index,2)
                self.assertEqual(app.parameter_controls[key].entry_var.get(),'-')
                self.assertEqual(app.zoom,2.5);self.assertEqual(app.canvas_origin,(-31,42))
                app._switch_workspace('yuv')
                self.assertEqual(app.yuv_frame_spin.get(),'-')
                self.assertEqual(app.zoom,4);self.assertEqual(app.canvas_origin,(13,-12))
        finally:app.close()

    def test_shared_menu_reuses_panel_and_preserves_view_and_draft(self):
        from isp_tool.ui.app import ISPApplication
        root=tk.Tk();root.withdraw();app=ISPApplication(root)
        try:
            before=app.pipeline.snapshot()
            app._switch_workspace('grading');p=app.grading_workspace
            self.assertIs(p.tool_variable,app.tool_var)
            self.assertEqual(app.tool_var.get(),'grading')
            self.assertIn('手动调色',p.tool_selector.cget('text'))
            for selector in (app.tool_selector,p.tool_selector):
                self.assertEqual(selector.menu.index('end'),3)
                self.assertTrue(all(selector.menu.type(i)=='radiobutton' for i in range(4)))
            p.fit=False;p.zoom=4;p.offset=[-31,52]
            p.values['RGB'][0].set('-')
            app._switch_workspace('isp')
            self.assertEqual(app.tool_var.get(),'isp')
            self.assertFalse(p.winfo_manager())
            app._switch_workspace('grading')
            self.assertIs(app.grading_workspace,p)
            self.assertEqual(p.zoom,4);self.assertEqual(p.offset,[-31,52])
            self.assertFalse(p.fit)
            self.assertEqual(p.values['RGB'][0].get(),'-')
            with mock.patch.object(app,'open_yuv_files') as open_yuv:
                app._switch_workspace('yuv');open_yuv.assert_called_once()
            # Cancelled import: menu must show the actual surviving workspace.
            self.assertEqual(app.tool_var.get(),'isp')
            self.assertEqual(app.pipeline.snapshot(),before)
        finally:app.close()


if __name__=='__main__':unittest.main()
