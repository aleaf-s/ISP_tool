import tempfile
import time
from pathlib import Path
from concurrent.futures import Future
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest import mock
import numpy as np
from PIL import Image
import tifffile
from isp_tool.awb_retune import (RetuneSettings, retune_screenshot, retune_bt709,
                                encode_bt709, decode_bt709, encode_srgb, decode_srgb)
from isp_tool.grading.image_io import ColorDocument, export_processed_image, read_color_image
from isp_tool.grading.model import raster8


class RetuneMathTests(unittest.TestCase):
    def test_identity_exact_and_gain_scale(self):
        source=np.random.default_rng(3).random((15,19,3),dtype=np.float32)
        settings=RetuneSettings((2345,1890),(2345,1890))
        np.testing.assert_array_equal(retune_screenshot(source,settings),source)
        np.testing.assert_array_equal(retune_bt709(source,settings),source)
        settings=RetuneSettings((2048,1024),(3072,512))
        np.testing.assert_array_equal(settings.transform(),np.diag([1.5,1,.5]))
        expected=encode_srgb(decode_srgb(source)*np.array([1.5,1,.5],np.float32))
        np.testing.assert_allclose(retune_screenshot(source,settings),expected,atol=2e-6)

    def test_nonidentity_ccm_matches_forward_camera_pipeline(self):
        scene=np.random.default_rng(7).uniform(.15,.3,(18,24,3)).astype(np.float32)
        matrix=np.array([[1.5,-.3,-.2],[-.1,1.3,-.2],[-.1,-.4,1.5]],np.float32)
        current=(1600,1400);target=(1700,1350)
        old_linear=(scene*np.array([current[0]/1024,1,current[1]/1024]))@matrix.T
        new_linear=(scene*np.array([target[0]/1024,1,target[1]/1024]))@matrix.T
        settings=RetuneSettings(current,target,tuple(map(tuple,matrix)))
        np.testing.assert_allclose(retune_bt709(encode_bt709(old_linear),settings),encode_bt709(new_linear),atol=3e-6)
        np.testing.assert_allclose(retune_screenshot(encode_srgb(old_linear),settings),encode_srgb(new_linear),atol=3e-6)
        # Explicit player conversion model equals the optimized screenshot path.
        screenshot=encode_srgb(old_linear)
        video=encode_bt709(decode_srgb(screenshot))
        reconstructed=encode_srgb(decode_bt709(retune_bt709(video,settings)))
        np.testing.assert_allclose(retune_screenshot(screenshot,settings),reconstructed,atol=3e-6)

    def test_signed_extended_curves_and_no_intermediate_clipping(self):
        linear=np.array([-3,-.4,-.01,0,.01,.2,1,4],np.float32)
        for enc,dec in ((encode_bt709,decode_bt709),(encode_srgb,decode_srgb)):
            np.testing.assert_allclose(dec(enc(linear)),linear,atol=2e-6)
        settings=RetuneSettings((1024,1024),(8192,1),((1.5,-.3,-.2),(-.1,1.3,-.2),(-.1,-.4,1.5)))
        out=retune_screenshot(np.array([[[1,.1,.1]]],np.float32),settings)
        self.assertTrue(np.isfinite(out).all())
        self.assertTrue(np.any(out>1));self.assertTrue(np.any(out<0))
        self.assertEqual(raster8(out).dtype,np.uint8)

    def test_invalid_gains_and_singular_ccm_rejected_even_identity(self):
        for gains in ((0,1024),(-1,1024),(1.5,1024),(65536,1024),(True,1024)):
            with self.assertRaises(ValueError):RetuneSettings(gains).transform()
        for matrix in (np.zeros((3,3)),np.diag([1,1,1e-8]),np.full((3,3),np.nan)):
            with self.assertRaises(ValueError):RetuneSettings(ccm=tuple(map(tuple,matrix))).transform()

    def test_export_identity_clipping_icc_and_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            rgba=np.full((13,17,4),(205,71,28,133),np.uint8)
            source=Path(folder)/'source.png';Image.fromarray(rgba).save(source)
            document=read_color_image(str(source))
            path=Path(folder)/'identity.png'
            export_processed_image(str(path),document,lambda x:retune_screenshot(x,RetuneSettings()))
            with Image.open(path) as picture:
                np.testing.assert_array_equal(np.array(picture),rgba)
                self.assertTrue(picture.info['icc_profile'])
            settings=RetuneSettings(target=(8192,512))
            path=Path(folder)/'changed.tif'
            export_processed_image(str(path),document,lambda x:retune_screenshot(x,settings))
            expected=np.rint(np.dstack((np.clip(retune_screenshot(document.rgb,settings),0,1),document.alpha))*65535).astype(np.uint16)
            np.testing.assert_array_equal(tifffile.imread(path),expected)


class RetuneWorkspaceTests(unittest.TestCase):
    def setUp(self):
        from isp_tool.ui.awb_retune_workspace import AWBRetuneWorkspace
        from isp_tool.ui.theme import configure_theme
        self.root=tk.Tk();self.root.withdraw();configure_theme(self.root)
        self.errors=[];self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.tool=tk.StringVar(self.root,value='awb_retune')
        self.calibration_folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.calibration_folder.cleanup)
        self.calibration_path=Path(self.calibration_folder.name)/'awb_ccm_calibration.json'
        self.panel=AWBRetuneWorkspace(self.root,self.tool,lambda tool:None,calibration_path=self.calibration_path)
        self.panel.set_document(ColorDocument('screenshot.png',np.full((48,64,3),(.7,.3,.2),np.float32),None,8,'sRGB'))
        self.wait_preview()

    def wait_preview(self):
        until=time.monotonic()+8
        while self.panel.future is not None and time.monotonic()<until:
            self.root.update();time.sleep(.01)
        self.assertIsNone(self.panel.future)

    def tearDown(self):
        self.panel.destroy();self.root.destroy();self.assertFalse(self.errors,self.errors)

    def test_drafts_apply_format_toggle_and_reset(self):
        from isp_tool.ui.widgets.ccm_matrix_editor import FLOAT,FIXED
        p=self.panel;initial=p.output.copy();revision=p.revision
        self.assertEqual(p.matrix_editor.variables[0].get(),'1024')
        p.gains['target'][0].set('2048');self.root.update()
        self.assertTrue(p.is_dirty());self.assertEqual(p.revision,revision)
        np.testing.assert_array_equal(p.output,initial)
        p.matrix_editor.set_mode(FLOAT);p.matrix_editor.set_mode(FIXED)
        self.assertEqual(p.revision,revision)
        p.apply();self.wait_preview();self.assertFalse(p.is_dirty())
        self.assertGreater(p.output[0,0,0],initial[0,0,0])
        revision=p.revision;p.apply();self.assertEqual(p.revision,revision)
        p.gains['current'][0].set('1800')
        self.assertEqual(p.gains['target'][0].get(),'2048')
        p.reset_target();self.assertEqual(p.gains['target'][0].get(),'1800')
        p.apply();self.wait_preview();np.testing.assert_array_equal(p.output,p.source)

    def test_invalid_drafts_never_apply_or_export(self):
        p=self.panel;revision=p.revision
        for text in ('','-','0','1.1','65536'):
            p.gains['target'][0].set(text);p.apply()
            self.assertEqual(p.revision,revision);self.assertTrue(p.error.get())
        p.gains['target'][0].set('1024')
        for var in p.matrix_editor.variables:var.set('0')
        p.apply();self.assertEqual(p.revision,revision)
        with mock.patch('isp_tool.ui.awb_retune_workspace.filedialog.asksaveasfilename') as dialog:
            p.export();dialog.assert_not_called()

    def test_latest_request_and_original_source(self):
        p=self.panel
        old=p.revision
        future=Future();p.future=future
        p.gains['target'][0].set('1500');p.apply()
        p.gains['target'][0].set('1800');p.apply()
        future.set_result((old,RetuneSettings(),np.zeros_like(p.source)))
        p.poll_preview();self.wait_preview()
        self.assertEqual(p.applied_settings.target,(1800,1024))
        np.testing.assert_allclose(p.output,retune_screenshot(p.source,p.applied_settings))
        p.gains['target'][0].set('1600');p.apply();self.wait_preview()
        np.testing.assert_allclose(p.output,retune_screenshot(p.source,p.applied_settings))

    def test_export_snapshot_and_pan_no_processing(self):
        p=self.panel;p.gains['target'][0].set('1800');p.apply();self.wait_preview()
        with mock.patch('isp_tool.ui.awb_retune_workspace.filedialog.asksaveasfilename',return_value='unused.png'),mock.patch('isp_tool.ui.awb_retune_workspace.export_processed_image') as export:
            p.export();p.io_future.result(timeout=5)
            process=export.call_args.args[2]
            np.testing.assert_array_equal(raster8(process(p.document.rgb)),raster8(p.output))
            p.gains['target'][0].set('2000')
            np.testing.assert_array_equal(raster8(process(p.document.rgb)),raster8(p.output))
        revision=p.revision;p.mode.set('滑动对比')
        with mock.patch.object(p.canvas,'winfo_width',return_value=640),mock.patch.object(p.canvas,'winfo_height',return_value=480):
            p.press(SimpleNamespace(x=320,y=20));self.assertEqual(p.drag[0],'split')
            p.motion(SimpleNamespace(x=250,y=20));p.wheel(SimpleNamespace(x=200,y=100,delta=120))
            p.zoom=32;p.fit=False;p.draw()
            self.assertTrue(all(photo.width()<=640 for photo in p._photos))
        self.assertEqual(p.revision,revision)


class RetuneIntegrationTests(unittest.TestCase):
    def test_all_tools_preserve_drafts_menus_and_pipeline(self):
        from isp_tool.ui.app import ISPApplication
        root=tk.Tk();root.withdraw();app=ISPApplication(root)
        try:
            pipeline=app.pipeline.snapshot();menu=root.cget('menu');shortcut=root.bind('<Control-o>')
            app._switch_workspace('awb_retune');p=app.awb_retune_workspace
            p.gains['target'][0].set('-');p.zoom=3;p.fit=False
            app._switch_workspace('grading');self.assertFalse(p.winfo_manager())
            app._switch_workspace('awb_retune');self.assertIs(app.awb_retune_workspace,p)
            self.assertFalse(app.grading_workspace.winfo_manager())
            self.assertEqual(p.gains['target'][0].get(),'-');self.assertEqual(p.zoom,3)
            app._switch_workspace('isp')
            self.assertEqual(root.cget('menu'),menu);self.assertEqual(root.bind('<Control-o>'),shortcut)
            self.assertEqual(app.pipeline.snapshot(),pipeline)
        finally:app.close()


if __name__=='__main__':unittest.main()
