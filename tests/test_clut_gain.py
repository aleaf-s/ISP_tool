"""CLUT Attr uses per-channel RGB displacement gain with a 512 unity code."""
from dataclasses import replace
from pathlib import Path
import tempfile
from unittest import TestCase, mock
import numpy as np
from PIL import Image
from tests import test_v0460
from isp_tool.grading.hsv_grid import HSVGrid, SHAPE, load_hsv, export_hsv
from isp_tool.grading.clut import build_clut, apply_clut
from isp_tool.grading.image_io import ColorDocument, export_processed_image
from isp_tool.grading.model import raster8


def adjusted_grid():
    a=np.array(HSVGrid().targets).reshape(*SHAPE,3)
    a[:,:,1:,0]+=35
    a[:,:,1:,1]*=.8
    return replace(HSVGrid(),targets=tuple(a.ravel()))


class GainMathTests(TestCase):
    def test_zero_disable_identity_and_no_absolute_rgb_gain(self):
        src=np.random.default_rng(61).random((9,13,3)).astype(np.float32)
        base=adjusted_grid()
        for grid in (replace(base,gains=(0,0,0)),replace(base,enabled=False),
                     replace(HSVGrid(),gains=(4095,256,1024))):
            np.testing.assert_allclose(apply_clut(src,build_clut(grid)),src,atol=2e-7)

    def test_rgb_gain_formula_after_interpolation_and_before_pixel_clip(self):
        src=np.random.default_rng(62).random((23,19,3)).astype(np.float32)
        base=adjusted_grid();unit=apply_clut(src,build_clut(base))
        for gains in ((256,256,256),(0,512,1024),(4095,3000,2048)):
            expected=np.clip(src+(unit-src)*np.array(gains)/512,0,1)
            result=apply_clut(src,build_clut(replace(base,gains=gains)))
            np.testing.assert_allclose(result,expected,atol=5e-7)
        amplified=build_clut(replace(base,gains=(4095,4095,4095)))
        self.assertTrue(np.any(amplified<0) or np.any(amplified>1))

    def test_channel_gains_are_independent_and_repeat_does_not_compound(self):
        src=np.array([[[.8,.2,.1],[.2,.8,.1],[.1,.2,.8]]],np.float32)
        base=adjusted_grid();full=apply_clut(src,build_clut(base))
        for c in range(3):
            gains=[0,0,0];gains[c]=512
            grid=replace(base,gains=tuple(gains));expected=src.copy();expected[...,c]=full[...,c]
            np.testing.assert_allclose(apply_clut(src,build_clut(grid)),expected,atol=2e-7)
            self.assertIs(build_clut(grid),build_clut(grid))
        self.assertEqual(base.targets,replace(base,gains=(256,256,256)).targets)

    def test_hsv_export_does_not_bake_runtime_gain_or_enable(self):
        base=adjusted_grid();grid=replace(base,gains=(256,1024,4095),enabled=False)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'hsv.txt';export_hsv(path,grid);first=path.read_bytes()
            loaded=load_hsv(path)
            self.assertEqual(loaded.targets,base.targets)
            self.assertEqual(loaded.gains,(512,512,512));self.assertTrue(loaded.enabled)
            export_hsv(path,base);self.assertEqual(path.read_bytes(),first)

    def test_gain_validation(self):
        for gains in ((-1,512,512),(4096,0,0),(1.5,2,3),(1,2),
                      (True,False,True),(float('nan'),0,0),('512',512,512)):
            with self.subTest(gains=gains),self.assertRaises(ValueError):replace(HSVGrid(),gains=gains)
        with self.assertRaises(ValueError):replace(HSVGrid(),enabled=1)


class GainWorkflowTests(TestCase):
    setUp=test_v0460.HSVOnlyWorkspaceTests.setUp
    tearDown=test_v0460.HSVOnlyWorkspaceTests.tearDown
    wait_preview=test_v0460.HSVOnlyWorkspaceTests.wait_preview
    enter=test_v0460.HSVOnlyWorkspaceTests.enter

    def test_gain_apply_image_export_undo_restore_and_image_isolation(self):
        e=self.enter();p=self.panel;p.clut_changed(adjusted_grid(),True)
        self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        original=p.output.copy();revision=p.revision
        e.gain_vars[0].set('256');e.gain_vars[1].set('0');e.gain_vars[2].set('1024')
        self.assertTrue(e.state.pending());self.assertTrue(e.commit_gains())
        self.assertEqual(p.revision,revision);np.testing.assert_array_equal(p.output,original)
        grid=e.state.grid;self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        expected=np.clip(p.document.rgb+(original-p.document.rgb)*np.array([.5,0,2]),0,1)
        np.testing.assert_allclose(p.output,expected,atol=5e-7)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'out.png';export_processed_image(path,p.document,p.preview_processor())
            np.testing.assert_array_equal(np.asarray(Image.open(path)),raster8(p.output))
        e.slide_gain(0,'128');self.assertEqual(e.state.grid.gains,(128,0,1024))
        e.travel(False);self.assertEqual(e.state.grid,grid)
        e.travel(True);self.assertEqual(e.gain_vars[0].get(),'128')
        p.restore_clut_applied();self.assertEqual(e.state.grid,grid);self.assertFalse(e.state.pending())
        p.documents.append(ColorDocument('second.png',p.document.rgb.copy(),None,8,'sRGB'))
        p.select_document(1);self.wait_preview();self.enter()
        self.assertEqual(e.state.grid.gains,(512,512,512))
        p.select_document(0);self.wait_preview();self.assertEqual(e.state.grid.gains,grid.gains)

    def test_invalid_gain_blocks_atomic_apply_and_draft_survives_switch(self):
        e=self.enter();p=self.panel;before=e.state.grid
        e.select_node(4,3);e.variables[0].set('16');e.gain_vars[1].set('2.5')
        self.assertFalse(e.commit_all());self.assertEqual(e.state.grid,before)
        self.assertIsNotNone(e.state.gain_draft)
        p.documents.append(ColorDocument('second.png',p.document.rgb.copy(),None,8,'sRGB'))
        p.select_document(1);self.wait_preview();self.enter()
        p.select_document(0);self.wait_preview()
        self.assertEqual(e.gain_vars[1].get(),'2.5')
        e.gain_vars[1].set('256');self.assertTrue(e.commit_all())
        self.assertEqual(e.state.grid.gains,(512,256,512))
        for i in range(9):self.assertEqual(e.state.grid.plane(i).dh[51],16)

    def test_disable_and_hsv_import_preserves_independent_attrs(self):
        e=self.enter();p=self.panel
        e.gain_vars[0].set('256');e.commit_gains()
        e.enabled_var.set(False);e.commit_enable()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'hsv.txt';export_hsv(path,adjusted_grid())
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(path)),\
                 mock.patch('isp_tool.ui.grading_workspace.messagebox.askyesno',return_value=True):p.load_hsv_file()
        self.assertEqual(e.state.grid.gains,(256,512,512));self.assertFalse(e.state.grid.enabled)
        self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        np.testing.assert_allclose(p.output,p.document.rgb,atol=2e-7)
        e.enabled_var.set(True);e.commit_enable()
        self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        self.assertGreater(float(np.max(abs(p.output-p.document.rgb))),.01)
