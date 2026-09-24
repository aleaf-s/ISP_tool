"""Original-resolution display/export agreement and fixed-centre navigation."""
import tempfile
import time
from pathlib import Path
from threading import Event
from concurrent.futures import CancelledError, Future
from types import SimpleNamespace
from unittest import TestCase, mock
import numpy as np
from PIL import Image
from isp_tool.grading.image_io import ColorDocument, export_processed_image
from isp_tool.grading.model import ColorPoint, build_lut, apply_lut, raster8
from isp_tool.grading.viewport import render_viewport
from isp_tool.awb_retune import RetuneSettings, retune_screenshot
from tests import test_v0444, test_v0446


class ViewportMathTests(TestCase):
    def setUp(self):
        self.rgb=np.random.default_rng(50).random((96,128,3),dtype=np.float32)
        self.doc=ColorDocument('detail.png',self.rgb,None,8,'sRGB')

    def test_grading_and_awb_native_pixels_match_export(self):
        lut=build_lut([ColorPoint((.7,.2,.1),(.9,.1,.05))])
        settings=RetuneSettings(target=(1900,750))
        for process in (lambda rgb:apply_lut(rgb,lut),lambda rgb:retune_screenshot(rgb,settings)):
            with self.subTest(process=process),tempfile.TemporaryDirectory() as folder:
                file=Path(folder)/'export.png'
                export_processed_image(file,self.doc,process)
                _,after=render_viewport(self.doc,process,(32,24),4,(-20,-10),(60,50),Event())
                with Image.open(file) as exported:
                    np.testing.assert_array_equal(np.asarray(after),np.asarray(exported)[10:60,20:80])

    def test_minification_happens_after_transform_and_quantization(self):
        process=lambda pixels:np.clip(pixels*1.8,0,1)
        _,after=render_viewport(self.doc,process,(32,24),1,(0,0),(32,24),Event())
        expected=Image.fromarray(raster8(process(self.rgb))).resize((32,24),Image.Resampling.LANCZOS)
        np.testing.assert_array_equal(after,expected)
        # Old thumbnail-first path loses bright-pixel clipping information.
        wrong=process(np.asarray(Image.fromarray(raster8(self.rgb)).resize((32,24),Image.Resampling.LANCZOS))/255)
        self.assertGreater(np.abs(np.asarray(after).astype(float)-raster8(wrong)).mean(),5)

    def test_zoom_processes_only_visible_original_pixels(self):
        shapes=[]
        def process(pixels):
            shapes.append(pixels.shape)
            return pixels
        before,after=render_viewport(self.doc,process,(32,24),8,(-80,-60),(96,64),Event())
        self.assertLess(sum(h*w for h,w,_ in shapes),self.rgb.shape[0]*self.rgb.shape[1])
        self.assertEqual(before.size,(96,64));np.testing.assert_array_equal(before,after)
        self.assertTrue(all(shape[0]<=128 for shape in shapes))

    def test_cancellation_between_processing_chunks(self):
        event=Event();calls=[]
        doc=ColorDocument('large.png',np.ones((600,200,3),np.float32),None,8,'sRGB')
        def process(pixels):
            calls.append(1);event.set();return pixels
        with self.assertRaises(CancelledError):
            render_viewport(doc,process,(200,600),1,(0,0),(200,600),event)
        self.assertEqual(len(calls),1)

    def test_alpha_negative_and_overflow_are_display_only(self):
        original=self.rgb.copy();self.doc.alpha=np.full(self.rgb.shape[:2],.5,np.float32)
        process=lambda pixels:pixels*4-1
        _,after=render_viewport(self.doc,process,(128,96),1,(0,0),(128,96),Event())
        expected=np.rint(raster8(process(self.rgb))*.5+56).astype(np.uint8)
        np.testing.assert_array_equal(after,expected);np.testing.assert_array_equal(self.doc.rgb,original)


class GradingDetailTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def wait_detail(self):
        until=time.monotonic()+8
        while time.monotonic()<until:
            self.root.update();time.sleep(.01)
            if getattr(self.panel,'_detail_key',None)==getattr(self.panel,'_detail_wanted_key',None) and getattr(self.panel,'_detail_key',None) is not None:
                return
        self.fail('Detail preview did not finish')

    def test_drag_disabled_centre_zoom_and_split_cache(self):
        p=self.panel;p.pick.set(False)
        with mock.patch.object(p.canvas,'winfo_width',return_value=640),mock.patch.object(p.canvas,'winfo_height',return_value=480):
            p.fit=False;p.zoom=2;p.draw();initial=p.offset.copy()
            p.press(SimpleNamespace(x=25,y=25));self.assertIsNone(p.drag)
            p.motion(SimpleNamespace(x=140,y=100));self.assertEqual(p.offset,initial)
            revision=p.revision
            p.wheel(SimpleNamespace(x=20,y=40,delta=120));p.draw()
            self.assertEqual(p.offset,[(640-p.source.shape[1]*p.zoom)/2,(480-p.source.shape[0]*p.zoom)/2])
            self.wait_detail()
            with mock.patch.object(p.executor,'submit',wraps=p.executor.submit) as submit:
                p.press(SimpleNamespace(x=320,y=50));p.motion(SimpleNamespace(x=200,y=50));p.draw()
                p.show_original(True);p.draw();p.show_original(False);p.draw()
                self.assertEqual(p._detail_key,p._detail_wanted_key);submit.assert_not_called()
            self.assertEqual(p.revision,revision)

    def test_hover_samples_original_not_thumbnail(self):
        p=self.panel;p.fit=False;p.zoom=1;p.offset=[0,0]
        p.document.rgb=np.full((96,120,3),(.2,.4,.6),np.float32)
        p.source[:]=0
        p.hover(SimpleNamespace(x=10,y=10))
        self.assertIn('Before RGB (51, 102, 153)',p.status.get())

    def test_remove_image_clears_detail_cache_and_queued_request(self):
        p=self.panel;p.draw();self.wait_detail()
        p.remove_document();p.draw()
        self.assertIsNone(p._detail_key);self.assertIsNone(p._detail_views)
        self.assertIsNone(p._detail_args);self.assertIsNone(p._detail_debounce)
        p.start_detail();self.assertIsNone(getattr(p,'_detail_future',None))

    def test_detail_latest_view_and_image_wins(self):
        p=self.panel;p.fit=False;p.zoom=2
        with mock.patch.object(p.canvas,'winfo_width',return_value=400),mock.patch.object(p.canvas,'winfo_height',return_value=300):
            p.draw();self.wait_detail()
            old=Future();p._detail_future=old;p._detail_cancel=Event();old_key=p._detail_running_key
            p.zoom=4;p.draw();self.assertTrue(p._detail_cancel.is_set())
            old.set_result((Image.new('RGB',(400,300),'red'),)*2)
            p.poll_detail();self.wait_detail()
            self.assertNotEqual(p._detail_key,old_key)
            self.assertEqual(p._detail_key,p._detail_wanted_key)


class AWBDetailTests(TestCase):
    setUp=test_v0446.RetuneWorkspaceTests.setUp
    tearDown=test_v0446.RetuneWorkspaceTests.tearDown
    wait_preview=test_v0446.RetuneWorkspaceTests.wait_preview

    def test_no_pan_and_processor_uses_applied_not_draft(self):
        p=self.panel;p.fit=False;p.zoom=2
        p.press(SimpleNamespace(x=30,y=30));self.assertIsNone(p.drag)
        offset=p.offset.copy();p.motion(SimpleNamespace(x=90,y=40));self.assertEqual(p.offset,offset)
        process=p.preview_processor();p.gains['target'][0].set('1900')
        np.testing.assert_array_equal(process(p.document.rgb),p.document.rgb)
        p.apply();self.wait_preview()
        np.testing.assert_array_equal(p.preview_processor()(p.document.rgb),retune_screenshot(p.document.rgb,p.applied_settings))

    def test_failed_stale_fast_task_continues_latest(self):
        p=self.panel;old=Future();p.future=old;p._running_revision=p.revision
        p.gains['target'][0].set('1600');p.apply()
        old.set_exception(ValueError('old failure'));p.poll_preview();self.wait_preview()
        self.assertEqual(p.applied_settings.target,(1600,1024))
