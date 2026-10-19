"""Three-dimensional HSV editing, lossless TXT records and explicit limitations."""
from pathlib import Path
from unittest import TestCase, mock
from dataclasses import replace
import tempfile
import numpy as np
import cv2
from isp_tool.grading.hsv_grid import (HSVGrid, SHAPE, VALUES, SATS, load_hsv,
    export_hsv, locate, influence)
from isp_tool.grading.clut import build_clut, apply_clut, HSGrid
from isp_tool.grading.hisi_clut import export_hisi, read_words
from tests import test_v0444


class HSVMathTests(TestCase):
    def test_one_node_and_value_locality(self):
        grid=HSVGrid().patch('dh',0,7,[[10]],index=4)
        targets=np.asarray(grid.targets).reshape(*SHAPE,3)
        identity=np.asarray(HSVGrid().targets).reshape(*SHAPE,3)
        self.assertEqual(np.count_nonzero(np.any(targets!=identity,axis=-1)),1)
        self.assertEqual(targets[4,0,7,0],10)
        hsv=np.array([[[0,.745,.25],[0,.745,.5],[0,.745,.75]]],np.float32)
        rgb=cv2.cvtColor(hsv,cv2.COLOR_HSV2RGB);out=apply_clut(rgb,build_clut(grid))
        np.testing.assert_allclose(out[0,[0,2]],rgb[0,[0,2]],atol=2e-7)
        self.assertGreater(float(np.linalg.norm(out[0,1]-rgb[0,1])),.01)
        weights=influence(hsv,4,0,7,0,1)
        np.testing.assert_allclose(weights,[[1,1,1]],atol=1e-6)
        self.assertEqual(locate(rgb[0,1]),(4,0,7))

    def test_identity_and_outer_node_do_not_change_rgb(self):
        rgb=np.random.default_rng(4).random((10,20,3)).astype(np.float32)
        np.testing.assert_allclose(apply_clut(rgb,build_clut(HSVGrid())),rgb,atol=2e-7)
        grid=HSVGrid().patch('dh',0,11,[[10]],index=4)
        np.testing.assert_allclose(apply_clut(rgb,build_clut(grid)),rgb,atol=1e-6)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.txt';export_hisi(path,grid)
            self.assertEqual(len(read_words(path)),5508)
            self.assertFalse(np.any(read_words(path)))

    def test_txt_edited_roundtrip_and_validation(self):
        grid=HSVGrid().patch('dh',0,7,[[10]],index=4)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.txt';export_hsv(path,grid);loaded=load_hsv(path)
            self.assertEqual(loaded.targets,grid.targets)
            self.assertEqual(path.read_text().count('{'),2700)
            text=path.read_text();path.write_text(text.replace('{ 0,  0,  0,','{ 0,  1,  0,',1))
            with self.assertRaises(ValueError):load_hsv(path)
            path.write_text(text.replace('Sat Tab 12','Sat Tab 11'))
            with self.assertRaises(ValueError):load_hsv(path)
        with self.assertRaises(ValueError):grid.patch('ds',0,11,[[-2]],index=4)
        with self.assertRaises(ValueError):grid.patch('dh',0,7,[[float('nan')]],index=4)

    def test_user_samples_exact_roundtrip(self):
        for name in ('74HS.txt','10HSV.txt','222HSV.txt','222HS.txt'):
            path=Path('C:/Users/remo/Downloads')/name
            if not path.exists():continue
            with self.subTest(file=name),tempfile.TemporaryDirectory() as folder:
                grid=load_hsv(path);out=Path(folder)/'out.txt';export_hsv(out,grid)
                self.assertEqual(path.read_bytes(),out.read_bytes())
                self.assertEqual(load_hsv(out).targets,grid.targets)
                if name=='74HS.txt':
                    self.assertEqual(grid.plane(4).dh[7],10)
                    self.assertEqual(grid.plane(3).dh[7],0)
                if name=='222HSV.txt':
                    self.assertFalse(grid.preview_supported)
                    with self.assertRaises(ValueError):build_clut(grid)
                    with self.assertRaises(ValueError):export_hisi(out,grid)


class HSVWorkflowTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def enter(self):
        p=self.panel;p.method.set('HSV 调色');p.switch_method();self.wait_preview()
        return p.clut_editor

    def test_layer_switch_apply_only_and_history(self):
        e=self.enter();p=self.panel;revision=p.revision
        e.select_node(0,7);e.variables[0].set('10');self.assertTrue(e.commit_node())
        e.value.set('.25');e.change_slice()
        self.assertEqual(e.state.slice_index,4);self.assertEqual(e.node_values(),(10.,0.))
        e.variables[0].set('5');e.commit_node()
        self.assertEqual(e.state.grid.plane(4).dh[7],5)
        self.assertEqual(e.state.grid.plane(2).dh[7],5)
        self.assertEqual(p.revision,revision)
        e.travel(False);self.assertEqual(e.state.grid.plane(2).dh[7],10)
        p.apply_clut_parameters();self.wait_preview()
        self.assertIsInstance(e.state.applied_grid,HSVGrid)
        self.assertEqual(e.state.applied_grid.plane(4).dh[7],10)
        e.variables[0].set('-');e.value.set('.5');e.change_slice()
        self.assertEqual(e.state.slice_index,4);self.assertEqual(e.variables[0].get(),'-')
        p.restore_clut_applied();self.assertFalse(e.state.drafts)

    def test_multi_layer_drafts_atomic_apply(self):
        e=self.enter()
        e.state.drafts={(4,0,7):('10','0'),(2,0,7):('-','0')}
        e.show_node();self.assertFalse(self.panel.apply_clut_parameters())
        self.assertEqual(e.state.grid.targets,HSVGrid().targets)
        e.state.drafts[(2,0,7)]=('5','0')
        self.assertFalse(self.panel.apply_clut_parameters())
        del e.state.drafts[(2,0,7)]
        self.assertTrue(self.panel.apply_clut_parameters());self.wait_preview()
        self.assertEqual(e.state.applied_grid.plane(4).dh[7],10)
        self.assertEqual(e.state.applied_grid.plane(2).dh[7],10)

    def test_import_export_and_unconfirmed_fields_guard(self):
        e=self.enter();p=self.panel
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.txt';dest=Path(folder)/'dest.txt'
            grid=HSVGrid().patch('dh',0,7,[[10]],index=4);export_hsv(source,grid)
            revision=p.revision
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.askopenfilename',return_value=str(source)),mock.patch('isp_tool.ui.grading_workspace.messagebox.askyesno',return_value=True):
                p.load_hsv_file()
            self.assertEqual(e.state.grid.targets,grid.targets);self.assertEqual(p.revision,revision)
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(dest)):
                p.save_hsv_file()
            self.assertEqual(dest.read_bytes(),source.read_bytes())
            a=np.asarray(grid.targets).copy();a[2]=.01
            e.state.replace(replace(grid,targets=tuple(a)));e.show_node()
            self.assertFalse(p.apply_clut_parameters());self.assertEqual(p.revision,revision)
            self.assertIn('第三字段',p.error.get())
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(dest)):
                p.save_hsv_file()
            self.assertEqual(load_hsv(dest).targets,e.state.grid.targets)

    def test_pick_locates_value_and_does_not_create_legacy_history(self):
        e=self.enter();p=self.panel
        with mock.patch.object(p,'open_clut_window'):p.pick_clut_at(20,20)
        vi,r,c=locate(p.state_for(p.document).clut.sample_rgb)
        self.assertEqual(e.state.slice_index,4);self.assertEqual(e.state.selected,(r,c))
        self.assertEqual(e.shape,(25,12))
        e.travel(False);self.assertIsInstance(e.state.grid,HSVGrid);self.assertEqual(e.shape,(25,12))
