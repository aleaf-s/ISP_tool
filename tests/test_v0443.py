import copy
import itertools
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import colour
import numpy as np
import tifffile
from PIL import Image

from isp_tool.pipeline import ISPPipeline
from isp_tool.raw_io import synthetic_bayer
from isp_tool.models import RawMetadata, ImageROI
from isp_tool.preview import display_rgb, encode_display_uint8, encode_display_rgb, export_image, export_stage_data
from isp_tool.exporting import export_pipeline_stage
from isp_tool.calibration.colorchecker import colorchecker_reference, reference_conditions, reorder_reference_indices
from isp_tool.calibration.delta_e import linear_srgb_to_lab, D65_XY
from isp_tool.calibration.ccm_solver import _delta_e
from isp_tool.calibration.srgb_gamut import srgb_ab_boundary, ab_background, lab_to_linear_srgb


class ExportTests(unittest.TestCase):
    def test_png_tiff_encoding_ev_order_and_computation_values(self):
        source = np.array([[[-.1, .18, 1.2], [.7, .01, .04]]], np.float32)
        original = source.copy()
        metadata = RawMetadata(width=2, height=1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            export_image(str(path/'预览.png'), source, 'rgb', metadata, exposure_ev=.5)
            with Image.open(path/'预览.png') as saved:
                np.testing.assert_array_equal(np.array(saved), encode_display_uint8(np.clip(source, 0, 1), .5))
                self.assertTrue(saved.info['icc_profile'])
            export_image(str(path/'view.tif'), source, 'rgb', metadata, exposure_ev=.5)
            expected = np.round(encode_display_rgb(np.clip(source, 0, 1), .5)*65535).astype(np.uint16)
            np.testing.assert_array_equal(tifffile.imread(path/'view.tif'), expected)
            export_stage_data(str(path/'data.tif'), source, 'rgb', metadata)
            np.testing.assert_array_equal(tifffile.imread(path/'data.tif'), source)
            export_image(str(path/'yuv.png'), source, 'yuv_rgb', metadata)
            np.testing.assert_array_equal(np.array(Image.open(path/'yuv.png')), encode_display_uint8(source, already_encoded=True))
        np.testing.assert_array_equal(source, original)

    def test_all_32_bypass_combinations_and_every_stage_export(self):
        loaded = synthetic_bayer(32, 24)
        pipeline = ISPPipeline(backend_preference='OpenCV / NumPy')
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'stage.png')
            for enabled in itertools.product((False, True), repeat=5):
                snapshot = pipeline.snapshot()
                for item, flag in zip(snapshot, enabled):
                    item['enabled'] = flag
                stages = pipeline.process(loaded.image, loaded.domain, loaded.metadata, snapshot)
                for stage in stages:
                    export_pipeline_stage(path, loaded.image, loaded.domain, loaded.metadata,
                                          snapshot, stage.module_id, .25, backend_preference='OpenCV / NumPy')
                    expected = encode_display_uint8(display_rgb(stage.image, stage.domain, loaded.metadata,
                                                                 data_state=stage.data_state), .25)
                    with Image.open(path) as saved:
                        np.testing.assert_array_equal(np.array(saved), expected)

    def test_odd_roi_preserves_bayer_phase_and_source_data(self):
        loaded = synthetic_bayer(32, 24)
        pipeline = ISPPipeline(backend_preference='OpenCV / NumPy')
        roi = ImageROI(3, 5, 9, 7)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'roi.png')
            export_pipeline_stage(path, loaded.image, loaded.domain, loaded.metadata, pipeline.snapshot(),
                                  'input', roi=roi, backend_preference='OpenCV / NumPy')
            expected = encode_display_uint8(display_rgb(loaded.image, 'bayer', loaded.metadata,
                                                        bayer_normalized=False))[roi.slices()]
            np.testing.assert_array_equal(np.array(Image.open(path)), expected)

    def test_yuv_full_stage_export_has_no_extra_transfer(self):
        from isp_tool.yuv import YUVMetadata
        from isp_tool.exporting import export_yuv_stage
        from isp_tool.ui.controllers.yuv_preview_controller import YUVPreviewController
        metadata = YUVMetadata(width=8, height=6, pixel_format='NV12', bit_depth=8)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'frame.yuv'
            source.write_bytes(bytes([100])*48 + bytes([140,110])*12)
            stages = YUVPreviewController.process(str(source), copy.deepcopy(metadata), 8, lambda: False)['results']
            for stage in stages:
                target = str(Path(folder)/'stage.png')
                export_yuv_stage(target, str(source), copy.deepcopy(metadata), stage.module_id, .25)
                expected = encode_display_uint8(np.clip(stage.image,0,1), .25, already_encoded=True)
                with Image.open(target) as saved:
                    np.testing.assert_array_equal(np.array(saved), expected)


class ReferenceAndGamutTests(unittest.TestCase):
    def test_spectral_lab_matches_direct_xyz_for_all_illuminants(self):
        cmfs = colour.MSDS_CMFS['CIE 1931 2 Degree Standard Observer']
        for illuminant in ('D65', 'D50', 'A'):
            names, rgb = colorchecker_reference(illuminant=illuminant)
            self.assertEqual((names[0], names[17]), ('dark skin', 'cyan'))
            xyz = np.array([colour.sd_to_XYZ(sd, cmfs=cmfs,
                illuminant=colour.SDS_ILLUMINANTS[illuminant])/100
                for sd in colour.SDS_COLOURCHECKERS['ColorChecker N Ohta'].values()])
            white = colour.CCS_ILLUMINANTS['CIE 1931 2 Degree Standard Observer'][illuminant]
            adapted = colour.adaptation.chromatic_adaptation_VonKries(xyz, colour.xy_to_XYZ(white),
                        colour.xy_to_XYZ(D65_XY), transform='CAT02')
            lab = colour.XYZ_to_Lab(adapted, illuminant=D65_XY)
            np.testing.assert_allclose(linear_srgb_to_lab(rgb), lab, atol=2e-5)
            self.assertEqual(reference_conditions(illuminant)['lab_white'], 'D65')
        for rotation in (0,90,180,270):
            for flipped in (True,False):
                self.assertEqual(sorted(reorder_reference_indices(rotation,flipped)), list(range(24)))

    def test_cyan_reference_is_not_clipped_in_metrics(self):
        from isp_tool.calibration.ccm_analysis import evaluate_matrix
        _, rgb = colorchecker_reference()
        self.assertLess(rgb[17, 0], 0)
        delta, lab, target = _delta_e(rgb, rgb)
        np.testing.assert_allclose(delta, 0, atol=1e-8)
        np.testing.assert_allclose(target, linear_srgb_to_lab(rgb), atol=1e-8)
        result = evaluate_matrix({'patches': [{'patch_id': 18, 'measured_rgb': rgb[17].tolist(),
            'reference_rgb': rgb[17].tolist(), 'diagnostics': {'valid': True}}]}, np.eye(3))
        np.testing.assert_allclose(result['patches'][0]['diagnostics']['reference_lab'], target[17])

    def test_true_gamut_section_and_cached_background(self):
        boundary = srgb_ab_boundary()
        self.assertIs(boundary, srgb_ab_boundary())
        lab = np.column_stack((np.full(len(boundary),70), boundary))
        rgb = lab_to_linear_srgb(lab)
        self.assertTrue(np.all((rgb >= -1e-7) & (rgb <= 1+1e-7)))
        self.assertTrue(np.all(np.min(np.minimum(abs(rgb),abs(rgb-1)), axis=1) < 1e-6))
        outside = lab.copy()
        outside[:,1:] *= 1.001
        rgb_out = lab_to_linear_srgb(outside)
        self.assertTrue(np.all(np.any((rgb_out < 0)|(rgb_out > 1), axis=1)))
        self.assertIs(ab_background(-70,85,-75,110), ab_background(-70,85,-75,110))


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        from isp_tool.ui.theme import configure_theme
        configure_theme(self.root)

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_chart_visibility_preserves_geometry_and_never_submits(self):
        from isp_tool.ui.app import ISPApplication
        app = ISPApplication(self.root)
        try:
            index = len(app.pipeline.modules)-1
            app.pipeline_list.selection_clear(0, 'end')
            app.pipeline_list.selection_set(index)
            app._on_module_select()
            app.colorchecker_edit_active = True
            app._set_colorchecker_corners([(10,10),(200,10),(200,140),(10,140)])
            before = copy.deepcopy(app.calibration_polygons)
            state = app.pipeline.snapshot()
            with mock.patch.object(app,'schedule_process') as process:
                app.colorchecker_visible_var.set(False)
                app._toggle_colorchecker_visibility()
                self.assertIsNone(app._colorchecker_hit_at((10,10)))
                self.assertEqual(before, app.calibration_polygons)
                app.colorchecker_visible_var.set(True)
                app._toggle_colorchecker_visibility()
                self.assertIsNotNone(app._colorchecker_hit_at((10,10)))
                process.assert_not_called()
                self.assertEqual(state, app.pipeline.snapshot())
        finally:
            app.close()

    def test_analysis_standard_symbols_and_no_formula_footer(self):
        from isp_tool.ui.ccm_analysis_window import CCMAnalysisWindow
        from tests.test_v0441 import chart_measurements
        window = CCMAnalysisWindow(self.root)
        window.set_result({**chart_measurements(), 'reference_conditions': reference_conditions()})
        self.assertEqual(window.tree.heading('deab','text'), 'ΔE*ab')
        self.assertEqual(window.tree.heading('dcab','text'), '‖Δab‖')
        self.assertIn('N Ohta', window.reference_var.get())
        window.deiconify()
        self.root.update()
        with mock.patch.object(window.ab_canvas, 'winfo_width', return_value=600), \
             mock.patch.object(window.ab_canvas, 'winfo_height', return_value=600):
            window._draw_ab()
        self.assertTrue(window.ab_canvas.find_withtag('srgb_boundary'))
        self.assertFalse(any('DEab =' in str(w.cget('text')) for w in window.winfo_children() if 'text' in w.keys()))

    def test_export_submits_full_source_and_frozen_snapshot(self):
        from isp_tool.ui.app import ISPApplication
        app = ISPApplication(self.root)
        try:
            deadline = time.monotonic()+8
            while not app.results and time.monotonic()<deadline:
                self.root.update()
                time.sleep(.01)
            module = app.pipeline.modules[-1]
            app.stage_combo.current(len(app.pipeline.modules))
            module.parameters['m00'] = 1.234
            with mock.patch('isp_tool.ui.app.filedialog.asksaveasfilename',return_value='test.png'), \
                 mock.patch.object(app.io_executor,'submit') as submit:
                app._export_selected_stage()
                args = submit.call_args.args
                self.assertIs(args[2], app.loaded.image)
                self.assertEqual(args[6], module.module_id)
                self.assertEqual(args[5][-1]['parameters']['m00'], 1.234)
                module.parameters['m00'] = 1.8
                self.assertEqual(args[5][-1]['parameters']['m00'], 1.234)
                self.assertIsNone(args[8])
        finally:
            app.close()


if __name__ == '__main__':
    unittest.main()
