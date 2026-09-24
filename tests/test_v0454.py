"""CA TXT layout, smooth interpolation, preview/export and per-image draft state."""
import tempfile
from pathlib import Path
from unittest import TestCase, mock

import numpy as np
from PIL import Image

from isp_tool.grading.ca import CACurve, CAState, apply_ca, export_ca_text, load_ca_text
from isp_tool.grading.image_io import ColorDocument, export_processed_image
from isp_tool.grading.model import raster8
from tests import test_v0444


class CAMathTests(TestCase):
    def test_exact_txt_roundtrip_and_rejection(self):
        values = tuple(min(2047, round(x*2047/255)) for x in range(256))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'data.txt'
            export_ca_text(path, CACurve.from_values(values))
            self.assertEqual(len(path.read_text().splitlines()),16)
            self.assertEqual(path.read_text().count(','),255)
            self.assertEqual(load_ca_text(path).values, values)
            original = path.read_bytes()
            with self.assertRaises(ValueError):export_ca_text(path,CACurve.from_values(values[:-1]))
            self.assertEqual(path.read_bytes(),original)
            path.write_text('0, 1, 2')
            with self.assertRaises(ValueError):load_ca_text(path)

    def test_shape_preserving_curve_endpoints_and_history(self):
        curve = CACurve().set_point(128,1800)
        self.assertEqual(curve.values[128],1800)
        self.assertEqual(curve.values[112],1024)
        self.assertEqual(curve.values[144],1024)
        self.assertTrue(all(1024 <= x <= 1800 for x in curve.values[112:145]))
        self.assertLess(max(abs(a-b) for a,b in zip(curve.values[112:144],curve.values[113:145])),100)
        self.assertEqual(curve.set_point(128,1800),curve)
        curve=curve.set_point(130,1700).remove_point(130)
        self.assertEqual(curve.values[128],1800)
        state=CAState();self.assertTrue(state.replace(curve));self.assertTrue(state.travel())
        self.assertEqual(state.curve,CACurve());self.assertTrue(state.travel(True))
        with self.assertRaises(ValueError):curve.remove_point(0)

    def test_uv_gain_uses_luma_neutral_and_identity(self):
        rgb=np.array([[[.8,.2,.1],[.4,.4,.4],[.1,.2,.8]]],np.float32)
        np.testing.assert_allclose(apply_ca(rgb,CACurve()),rgb,atol=2e-7)
        changed=CACurve.from_values((2047,)*256)
        out=apply_ca(rgb,changed)
        self.assertLess(out[0,0,1],rgb[0,0,1])
        np.testing.assert_allclose(out[0,1],rgb[0,1],atol=2e-7)
        self.assertGreater(out[0,2,2],rgb[0,2,2])
        np.testing.assert_array_equal(rgb,np.array([[[.8,.2,.1],[.4,.4,.4],[.1,.2,.8]]],np.float32))


class CAWorkflowTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def enter_ca(self):
        p=self.panel;p.method.set('CA 调色');p.switch_method();self.wait_preview()
        return p.ca_editor

    def test_apply_only_restore_and_invalid_draft(self):
        p=self.panel;editor=self.enter_ca();before=p.output.copy();revision=p.revision
        editor.x_var.set('80');editor.y_var.set('1500');self.assertTrue(editor.set_point())
        self.assertEqual(p.revision,revision)
        self.assertEqual(p.state_for(p.document).ca.applied,CACurve())
        editor.y_var.set('-')
        self.assertFalse(p.apply_ca_parameters())
        self.assertEqual(p.revision,revision)
        p.restore_ca_applied()
        self.assertEqual(p.state_for(p.document).ca.curve,CACurve())
        np.testing.assert_array_equal(p.output,before)
        editor.y_var.set('1500');self.assertTrue(p.apply_ca_parameters());self.wait_preview()
        self.assertEqual(p.state_for(p.document).ca.applied.values[80],1500)
        self.assertFalse(np.array_equal(p.output,before))

    def test_txt_import_export_and_image_agree(self):
        p=self.panel;self.enter_ca()
        curve=CACurve.from_values((2047,)*256)
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'ca.txt';out=Path(folder)/'out.txt';image=Path(folder)/'out.png'
            export_ca_text(source,curve)
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(source)):
                p.load_ca_file()
            self.assertEqual(p.state_for(p.document).ca.curve,curve)
            self.assertEqual(p.state_for(p.document).ca.applied,CACurve())
            p.apply_ca_parameters();self.wait_preview()
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(out)):
                p.export_ca_file()
            self.assertEqual(load_ca_text(out),curve)
            export_processed_image(image,p.document,p.preview_processor())
            np.testing.assert_array_equal(np.asarray(Image.open(image)),raster8(apply_ca(p.document.rgb,curve)))

    def test_images_keep_separate_ca_curves(self):
        p=self.panel;editor=self.enter_ca();first=p.document
        editor.x_var.set('80');editor.y_var.set('1500');editor.set_point();p.apply_ca_parameters();self.wait_preview()
        second=ColorDocument('other.png',first.rgb.copy(),None,8,'sRGB')
        p.documents.append(second);p.select_document(1);self.wait_preview()
        self.assertEqual(p.state_for(second).ca.curve,CACurve())
        p.select_document(0);self.wait_preview()
        self.assertEqual(p.state_for(first).ca.applied.values[80],1500)

    def test_unsubmitted_text_survives_image_switch_and_blocks_export(self):
        p=self.panel;editor=self.enter_ca();first=p.document
        editor.y_var.set('-')
        self.assertEqual(p.ca_status.get(),'待应用')
        second=ColorDocument('other.png',first.rgb.copy(),None,8,'sRGB')
        p.documents.append(second);p.select_document(1);self.wait_preview()
        p.method.set('CA 调色');p.switch_method();self.wait_preview()
        self.assertEqual(editor.y_var.get(),'1024')
        p.select_document(0);self.wait_preview()
        self.assertEqual(editor.y_var.get(),'-')
        with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename') as dialog:
            p.export_ca_file()
            dialog.assert_not_called()
        self.assertTrue(p.error.get())
        p.restore_ca_applied()
        self.assertEqual(editor.y_var.get(),'1024')
        self.assertEqual(p.ca_status.get(),'已应用')
