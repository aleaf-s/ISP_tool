import copy
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import numpy as np
import tifffile
from PIL import Image, ImageCms
from isp_tool.grading.model import ColorPoint, GradeHistory, build_lut, apply_lut, raster8, sample_original
from isp_tool.grading.image_io import ColorDocument, read_color_image, export_color_image


class GradingTests(unittest.TestCase):
    def test_identity_boundaries_and_interpolation(self):
        rgb=np.random.default_rng(4).random((31,29,3)).astype(np.float32)
        lut=build_lut([])
        np.testing.assert_allclose(apply_lut(rgb,lut),rgb,atol=2e-7)
        np.testing.assert_array_equal(raster8(apply_lut(rgb,lut)),raster8(rgb))
        corners=np.array([[[0,0,0],[1,1,1],[1,0,0],[0,1,0],[0,0,1]]],np.float32)
        np.testing.assert_array_equal(apply_lut(corners,lut),corners)
        np.testing.assert_allclose(apply_lut(rgb,lut[...,::-1]),rgb[...,::-1],atol=2e-7)

    def test_multiple_anchors_gray_protection_and_zero_strength(self):
        points=[ColorPoint((.8,.2,.1),(.65,.3,.2)),ColorPoint((.1,.3,.8),(.15,.5,.7))]
        source=np.array([[p.source for p in points]],np.float32)
        output=apply_lut(source,build_lut(points))
        self.assertTrue(np.all(np.linalg.norm(output-source,axis=-1)>.08))
        neutral=np.repeat(np.linspace(0,1,65)[:,None],3,axis=1)[None,...].astype(np.float32)
        # Exact diagonal LUT samples remain neutral; interpolation near the
        # diagonal may deviate slightly, hence the sub-code-value tolerance.
        np.testing.assert_allclose(apply_lut(neutral,build_lut(points)),neutral,atol=.001)
        points[0].strength=points[1].strength=0
        np.testing.assert_allclose(apply_lut(source,build_lut(points)),source,atol=2e-7)

    def test_locality_and_red_seam(self):
        point=ColorPoint((.8,.1,.1),(.6,.2,.15),radius=10)
        rgb=np.array([[[.8,.101,.1],[.8,.1,.101],[.1,.1,.8]]],np.float32)
        out=apply_lut(rgb,build_lut([point]))
        self.assertLess(np.linalg.norm(out[0,0]-out[0,1]),.005)
        np.testing.assert_allclose(out[0,2],rgb[0,2],atol=.002)

    def test_history_source_and_sample(self):
        history=GradeHistory()
        point=ColorPoint((.2,.3,.4),(.3,.4,.5))
        history.replace([point])
        point.target=(1,0,0)
        self.assertEqual(history.points[0].target,(.3,.4,.5))
        self.assertTrue(history.undo());self.assertEqual(history.points,[])
        self.assertTrue(history.redo())
        self.assertFalse(history.replace(copy.deepcopy(history.points)))
        history.undo();history.replace([point]);self.assertFalse(history.redo_stack)
        image=np.zeros((7,7,3),np.float32);image[3,3]=1
        np.testing.assert_allclose(sample_original(image,3,3),(1/25,)*3)

    def test_io_icc_alpha_16_bit_and_exact_export(self):
        rgb=np.random.default_rng(2).integers(0,65536,(20,24,3),dtype=np.uint16)
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            tifffile.imwrite(folder/'source.tif',rgb,photometric='rgb')
            doc=read_color_image(str(folder/'source.tif'))
            self.assertEqual(doc.bit_depth,16)
            np.testing.assert_allclose(doc.rgb,rgb/65535,atol=3e-8)
            lut=build_lut([ColorPoint((.8,.2,.1),(.7,.3,.1))])
            export_color_image(str(folder/'out.png'),doc,lut)
            np.testing.assert_array_equal(np.array(Image.open(folder/'out.png')),raster8(apply_lut(doc.rgb,lut)))
            export_color_image(str(folder/'out.tif'),doc,lut)
            np.testing.assert_array_equal(tifffile.imread(folder/'out.tif'),np.rint(apply_lut(doc.rgb,lut)*65535).astype(np.uint16))
            rgba=np.zeros((8,9,4),np.uint8);rgba[...,:3]=[128,34,201];rgba[...,3]=150
            icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
            Image.fromarray(rgba).save(folder/'rgba.png',icc_profile=icc)
            doc=read_color_image(str(folder/'rgba.png'))
            self.assertIn('ICC',doc.note)
            export_color_image(str(folder/'alpha.png'),doc,build_lut([]))
            np.testing.assert_array_equal(np.array(Image.open(folder/'alpha.png')),rgba)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        from isp_tool.ui.grading_workspace import GradingWorkspace
        from isp_tool.ui.theme import configure_theme
        self.root=tk.Tk();self.root.withdraw();configure_theme(self.root)
        self.errors=[]
        self.root.report_callback_exception=lambda *a:self.errors.append(a)
        self.panel=GradingWorkspace(self.root,lambda:None)
        self.panel.pack(fill='both',expand=True)
        rgb=np.full((64,80,3),(.8,.2,.1),np.float32)
        self.panel.documents=[ColorDocument('synthetic.png',rgb,None,8,'sRGB')]
        self.panel.select_document(0)
        self.wait_preview()

    def wait_preview(self):
        until=time.monotonic()+8
        while self.panel.future is not None and time.monotonic()<until:
            self.root.update();time.sleep(.01)
        self.assertIsNone(self.panel.future)

    def tearDown(self):
        self.panel.destroy();self.root.destroy()
        self.assertFalse(self.errors,self.errors)

    def test_numeric_commit_dedupe_undo_and_latest_request(self):
        p=self.panel
        p.selected=0
        p.edit([ColorPoint((.8,.2,.1),(.8,.2,.1))])
        original=p.document.rgb.copy()
        for var,value in zip(p.values['RGB'],('160','90','40')):var.set(value)
        p.commit_target('RGB')
        count=len(p.history.undo_stack)
        p.commit_target('RGB')
        self.assertEqual(len(p.history.undo_stack),count)
        p.values['HSV'][0].set('-')
        p.commit_target('HSV')
        self.assertTrue(p.error.get())
        self.assertEqual(len(p.history.undo_stack),count)
        p.show_point()
        for value in (30,50,80):
            p.strength.set(str(value));p.commit_influence()
        self.wait_preview()
        self.assertEqual(p._shown_revision,p.revision)
        np.testing.assert_allclose(p.output,apply_lut(p.source,build_lut(p.history.points)))
        np.testing.assert_array_equal(p.document.rgb,original)
        p.travel(False);self.assertEqual(p.history.points[0].strength,.5)
        p.travel(True);self.assertEqual(p.history.points[0].strength,.8)

    def test_pick_uses_original_and_split_drag_does_not_add_point(self):
        p=self.panel
        p.offset=[0,0];p.zoom=1;p.fit=False;p.pick.set(True)
        p.output[:]=0
        with mock.patch.object(p.canvas,'winfo_width',return_value=160):
            p.press(SimpleNamespace(x=10,y=10))
        np.testing.assert_allclose(p.history.points[0].source,(.8,.2,.1),atol=1e-6)
        p.mode.set('滑动对比');p.pick.set(True)
        with mock.patch.object(p.canvas,'winfo_width',return_value=160):
            p.press(SimpleNamespace(x=80,y=10))
        self.assertEqual(p.drag[0],'split')
        self.assertEqual(len(p.history.points),1)

    def test_zoom_render_is_viewport_bounded_and_does_not_process(self):
        p=self.panel;p.zoom=32;p.fit=False;p.offset=[-100,-200]
        revision=p.revision
        with mock.patch.object(p.canvas,'winfo_width',return_value=640),mock.patch.object(p.canvas,'winfo_height',return_value=480):
            p.draw()
        self.assertTrue(all(image.width()<=640 and image.height()<=480 for image in p._photos))
        self.assertEqual(p.revision,revision)

    def test_export_validates_visible_draft_even_without_focusout(self):
        p=self.panel;p.selected=0
        p.edit([ColorPoint((.8,.2,.1),(.8,.2,.1))])
        with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value='') as dialog:
            p.values['RGB'][0].set('-')
            p.export();dialog.assert_not_called()
            p.values['RGB'][0].set('100')
            p.export();dialog.assert_called_once()
            self.assertAlmostEqual(p.history.points[0].target[0],100/255)


class AppIntegrationTests(unittest.TestCase):
    def test_embedded_workspace_restores_isp_menus_and_shortcuts(self):
        from isp_tool.ui.app import ISPApplication
        root=tk.Tk();root.withdraw()
        app=ISPApplication(root)
        try:
            before=app.pipeline.snapshot()
            menu=root.cget('menu');shortcut=root.bind('<Control-o>')
            app.open_grading_workspace()
            panel=app.grading_workspace
            self.assertEqual(panel.winfo_manager(),'place')
            self.assertNotEqual(root.cget('menu'),menu)
            self.assertEqual(app.pipeline.snapshot(),before)
            app.close_grading_workspace()
            self.assertEqual(root.cget('menu'),menu)
            self.assertEqual(root.bind('<Control-o>'),shortcut)
            app.open_grading_workspace()
            self.assertIs(app.grading_workspace,panel)
            app.close_grading_workspace()
        finally:app.close()


if __name__=='__main__':unittest.main()
