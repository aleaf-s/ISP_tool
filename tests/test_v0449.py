"""Shared swatch catalogue, isolated image adjustments and navigation drafts."""
import copy
import tkinter as tk
from tkinter import ttk
from concurrent.futures import Future
from unittest import TestCase, mock
import numpy as np
from isp_tool.grading.image_io import ColorDocument
from isp_tool.grading.model import ColorPoint
from isp_tool.grading.session import processing_key
from tests import test_v0444 as previous


class IsolatedGradingTests(TestCase):
    setUp=previous.WorkspaceTests.setUp
    tearDown=previous.WorkspaceTests.tearDown
    wait_preview=previous.WorkspaceTests.wait_preview

    def add_b(self):
        p=self.panel
        b=ColorDocument('other/synthetic.png',p.document.rgb.copy(),None,8,'sRGB')
        p.documents.append(b)
        return b

    def add_point(self,target=(.6,.3,.2)):
        p=self.panel;p.save_draft();p.selected=len(p.history.points)
        p.edit(p.history.points+[ColorPoint((.8,.2,.1),target)])
        self.wait_preview()
        return p.selected_point().point_id

    def click_point(self,point_id):
        self.panel.point_list.selection_set(point_id)
        self.panel.select_point();self.root.update();self.wait_preview()

    def test_defaults_and_session_comparison_choice(self):
        p=self.panel;self.assertEqual(p.mode.get(),'滑动对比')
        self.assertEqual(p.divider,.5)
        self.add_b();p.mode.set('左右并排');p.select_document(1);self.wait_preview()
        self.assertEqual(p.mode.get(),'左右并排')
        p.select_document(0);self.wait_preview();self.assertEqual(p.mode.get(),'左右并排')

    def test_identical_images_never_share_adjustments_or_undo(self):
        p=self.panel;b=self.add_b();a=p.document
        aid=self.add_point();a_output=p.output.copy()
        p.select_document(1);self.wait_preview()
        np.testing.assert_array_equal(p.output,p.source)
        bid=self.add_point((.4,.5,.3));b_output=p.output.copy()
        self.assertEqual(len(p.point_list.get_children()),2)
        self.assertEqual(p.point_list.heading('#0','text'),'名称')
        self.assertEqual(p.point_list.heading('origin','text'),'来源')
        self.assertFalse(p.point_list.item(aid,'image'))
        self.click_point(aid)
        self.assertIs(p.document,a);np.testing.assert_array_equal(p.output,a_output)
        revision=p.revision;self.click_point(aid);self.assertEqual(p.revision,revision)
        p.delete_point();self.wait_preview();np.testing.assert_array_equal(p.output,p.source)
        self.click_point(bid);self.assertIs(p.document,b);np.testing.assert_array_equal(p.output,b_output)
        p.travel(False);self.wait_preview();self.assertFalse(p.history.points)
        p.select_document(0);self.wait_preview();p.travel(False);self.wait_preview()
        self.assertEqual(p.history.points[0].point_id,aid)
        np.testing.assert_array_equal(p.output,a_output)

    def test_per_image_bypass_and_cached_return(self):
        p=self.panel;self.add_b();self.add_point()
        p.enabled.set(False);p.toggle_enabled()
        p.select_document(1);self.wait_preview();self.assertTrue(p.enabled.get())
        with mock.patch.object(p.executor,'submit',wraps=p.executor.submit) as submit:
            p.select_document(0);self.wait_preview();submit.assert_not_called()
        self.assertFalse(p.enabled.get())

    def test_rename_cancel_validation_and_draft_preservation_no_processing(self):
        p=self.panel;point_id=self.add_point();source=p.selected_point().source
        p.values['RGB'][0].set('-');revision=p.revision;output=p.output.copy()
        p.rename_point(name=' 白箱子 ')
        self.assertEqual(p.selected_point().name,'白箱子')
        self.assertEqual(p.selected_point().source,source)
        self.assertEqual(p.selected_point().point_id,point_id)
        self.assertEqual(p.values['RGB'][0].get(),'-')
        self.assertTrue(p.has_draft());self.assertTrue(p.draft_status.get())
        p.rename_point(name=' ');self.assertTrue(p.error.get())
        with mock.patch('isp_tool.ui.grading_workspace.simpledialog.askstring',return_value=None):p.rename_point()
        self.assertEqual(p.selected_point().name,'白箱子')
        self.assertEqual(p.revision,revision);np.testing.assert_array_equal(p.output,output)
        p.travel(False);self.assertEqual(p.revision,revision)

    def test_per_point_valid_and_invalid_drafts_survive_navigation(self):
        p=self.panel;self.add_b();aid=self.add_point()
        p.values['RGB'][0].set('123');p.radius.set('-')
        before=copy.deepcopy(p.history.points)
        p.select_document(1);self.wait_preview();bid=self.add_point((.5,.5,.1))
        p.values['HSV'][0].set('.')
        self.click_point(aid)
        self.assertEqual(p.values['RGB'][0].get(),'123');self.assertEqual(p.radius.get(),'-')
        self.assertEqual(p.history.points,before)
        self.click_point(bid);self.assertEqual(p.values['HSV'][0].get(),'.')

    def test_focusout_queued_before_switch_cannot_commit_new_image(self):
        p=self.panel;self.add_b();self.add_point();p.values['RGB'][0].set('120')
        before=copy.deepcopy(p.history.points)
        dummy=ttk.Entry(p)
        with mock.patch.object(p,'winfo_ismapped',return_value=True),mock.patch.object(p,'focus_get',return_value=dummy):
            p.defer_commit(lambda:p.commit_target('RGB'))
            p.select_document(1);self.root.update();self.wait_preview()
        self.assertFalse(p.history.points)
        p.select_document(0);self.wait_preview()
        self.assertEqual(p.history.points,before);self.assertEqual(p.values['RGB'][0].get(),'120')
        with mock.patch.object(p,'winfo_ismapped',return_value=True),mock.patch.object(p,'focus_get',return_value=p.file_combo):
            p.defer_commit(lambda:p.commit_target('RGB'));self.root.update()
        self.assertEqual(p.history.points,before)
        with mock.patch.object(p,'winfo_ismapped',return_value=True),mock.patch.object(p,'focus_get',return_value=dummy):
            p.defer_commit(lambda:p.commit_target('RGB'));self.root.update()
        self.wait_preview();self.assertAlmostEqual(p.selected_point().target[0],120/255)

    def test_explicit_copy_is_independent_and_requires_committed_values(self):
        p=self.panel;b=self.add_b();aid=self.add_point();revision=p.revision
        p.copy_point_to(b.document_id)
        clone=p.state_for(b).history.points[0]
        self.assertNotEqual(clone.point_id,aid);self.assertEqual(clone.owner_id,b.document_id)
        self.assertEqual(clone.target,p.selected_point().target);self.assertEqual(p.revision,revision)
        p.values['RGB'][0].set('80');p.commit_target('RGB');self.wait_preview()
        self.assertNotEqual(clone.target,p.selected_point().target)
        p.values['RGB'][0].set('-');p.copy_point_to(b.document_id)
        self.assertEqual(len(p.state_for(b).history.points),1)
        self.click_point(clone.point_id);self.assertEqual(p.selected_point().target,clone.target)

    def test_foreign_owned_points_rejected_not_silently_shared(self):
        p=self.panel;self.add_b();self.add_point();points=copy.deepcopy(p.history.points)
        p.select_document(1);self.wait_preview()
        with self.assertRaises(ValueError):p.edit(points)
        self.assertFalse(p.history.points)

    def test_same_names_reorder_remove_and_reimport_use_stable_ids(self):
        p=self.panel;b=self.add_b();a=p.document;aid=self.add_point()
        p.select_document(1);self.wait_preview();bid=self.add_point((.3,.4,.2))
        p.documents.reverse();self.click_point(aid);self.assertIs(p.document,a)
        p.remove_document();self.wait_preview();self.assertIs(p.document,b)
        self.assertNotIn(a.document_id,p.states);self.assertNotIn(aid,p._point_rows)
        self.assertIn(bid,p._point_rows)
        replacement=ColorDocument(a.path,a.rgb,None,8,'sRGB');p.documents.append(replacement)
        p.select_document(1);self.wait_preview()
        self.assertNotEqual(replacement.document_id,a.document_id);self.assertFalse(p.history.points)
        np.testing.assert_array_equal(p.output,p.source)

    def test_late_deleted_image_result_cannot_recreate_state(self):
        p=self.panel;self.add_b();old_id=p.document.document_id;old_rev=p.revision
        old=Future();p.future=old
        p.remove_document()
        old.set_result((old_rev,old_id,(),np.zeros_like(p.source)))
        p.poll_preview();self.wait_preview()
        self.assertNotIn(old_id,p.states)
        np.testing.assert_array_equal(p.output,p.source)

    def test_late_failure_does_not_block_new_image(self):
        p=self.panel;self.add_b();old=Future();p.future=old;p._running_revision=p.revision
        p.select_document(1);old.set_exception(ValueError('old image'))
        p.poll_preview();self.wait_preview()
        self.assertNotEqual(p.error.get(),'old image')
        self.assertEqual(p._shown_revision,p.revision)

    def test_split_drag_and_pan_never_change_history_or_process(self):
        from types import SimpleNamespace
        p=self.panel;self.add_point();p.pick.set(True);revision=p.revision
        with mock.patch.object(p.canvas,'winfo_width',return_value=600):
            p.press(SimpleNamespace(x=300,y=20));self.assertEqual(p.drag[0],'split')
            p.motion(SimpleNamespace(x=220,y=20))
        self.assertEqual(len(p.history.points),1);self.assertEqual(p.revision,revision)


class AWBDefaultTests(TestCase):
    def test_sliding_default(self):
        import tempfile
        from pathlib import Path
        from isp_tool.ui.awb_retune_workspace import AWBRetuneWorkspace
        root=tk.Tk();root.withdraw()
        with tempfile.TemporaryDirectory() as folder:
            panel=AWBRetuneWorkspace(root,tk.StringVar(root,value='awb_retune'),lambda _:None,
                                     calibration_path=Path(folder)/'table.json')
            try:
                self.assertEqual(panel.mode.get(),'滑动对比');self.assertEqual(panel.divider,.5)
            finally:panel.destroy();root.destroy()
