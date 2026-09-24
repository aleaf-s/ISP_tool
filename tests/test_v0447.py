import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import numpy as np
from isp_tool.awb_ccm_table import CalibrationPoint, CalibrationTable, DEFAULT_FIXED, matrix_tuple
from isp_tool.awb_retune import RetuneSettings, retune_screenshot, encode_srgb
from isp_tool.ccm_encoding import encode_ccm
from isp_tool.ui.awb_retune_workspace import AUTO, SAME, MANUAL
from tests import test_v0446 as previous


class CalibrationMathTests(unittest.TestCase):
    def test_default_data_exact_lookup_and_row_sums(self):
        table=CalibrationTable.default()
        for p,raw in zip(table.points,DEFAULT_FIXED):
            self.assertEqual((p.cct,p.r_gain,p.b_gain),raw[:3])
            self.assertEqual(tuple(tuple(encode_ccm(v) for v in row) for row in p.ccm),raw[3])
            self.assertEqual(table.lookup(p.r_gain,p.b_gain).ccm,p.ccm)
            np.testing.assert_array_equal(np.asarray(p.ccm).sum(axis=1),np.ones(3))
            self.assertLess(np.linalg.cond(p.ccm),3)
        self.assertEqual(table.points[1].b_gain,3054)

    def test_log_projection_float_interpolation_and_mired(self):
        table=CalibrationTable.default();a,b=table.points[2:4];t=.4
        gain=np.exp((1-t)*np.log([a.r_gain,a.b_gain])+t*np.log([b.r_gain,b.b_gain]))
        result=table.lookup(*gain)
        self.assertAlmostEqual(result.fraction,t)
        self.assertAlmostEqual(result.cct,1/((1-t)/a.cct+t/b.cct))
        np.testing.assert_allclose(result.ccm,(1-t)*np.array(a.ccm)+t*np.array(b.ccm),atol=1e-13)
        # Interpolation across a sign change must cross zero, not the code wrap.
        a=CalibrationPoint(3000,1000,3000,((1,.1,0),(0,1,0),(0,0,1)))
        b=CalibrationPoint(6000,3000,1000,((1,-.1,0),(0,1,0),(0,0,1)))
        result=CalibrationTable((a,b)).lookup(np.sqrt(3e6),np.sqrt(3e6))
        self.assertAlmostEqual(result.ccm[0][1],0)

    def test_outside_and_off_track_do_not_extrapolate(self):
        table=CalibrationTable.default()
        result=table.lookup(600,8000)
        self.assertTrue(result.limited);self.assertEqual(result.ccm,table.points[0].ccm)
        result=table.lookup(8000,600)
        self.assertTrue(result.limited);self.assertEqual(result.ccm,table.points[-1].ccm)
        # Each component is inside its separate min/max; joint point is off locus.
        result=table.lookup(3000,3700)
        self.assertGreater(result.distance,.12);self.assertIn('偏离',result.warning)
        self.assertTrue(0<=result.fraction<=1)
        with self.assertRaises(ValueError):table.lookup(0,1024)

    def test_json_roundtrip_encodings_and_invalid_data(self):
        table=CalibrationTable.default()
        for encoding in ('float','fixed13'):
            restored=CalibrationTable.from_payload(json.loads(json.dumps(table.to_payload(encoding))))
            self.assertEqual(restored,table)
        payload=table.to_payload('fixed13')
        for key,value in (('gain_scale',1),('ccm_scale',1),('ccm_encoding','unknown'),('version',2)):
            broken=copy.deepcopy(payload);broken[key]=value
            with self.assertRaises(ValueError):CalibrationTable.from_payload(broken)
        broken=copy.deepcopy(payload);broken['points'][0]['ccm'][0][0]=8192
        with self.assertRaises(ValueError):CalibrationTable.from_payload(broken)
        broken=copy.deepcopy(payload);broken['ccm_encoding']='float';broken['ccm_scale']=1
        with self.assertRaises(ValueError):CalibrationTable.from_payload(broken)
        with self.assertRaises(ValueError):CalibrationTable((table.points[0],))
        with self.assertRaises(ValueError):CalibrationTable((table.points[0],table.points[0]))
        with self.assertRaises(ValueError):CalibrationPoint(3000,0,1024,np.eye(3))
        with self.assertRaises(ValueError):CalibrationPoint(3000,1024,1024,np.zeros((3,3)))
        duplicate=CalibrationPoint(9000,table.points[0].r_gain,table.points[0].b_gain,np.eye(3))
        with self.assertRaises(ValueError):CalibrationTable((table.points[0],duplicate))

    def test_matrix_changes_with_same_gain_and_combined_forward_pipeline(self):
        table=CalibrationTable.default();old,new=table.points[1],table.points[-1]
        scene=np.random.default_rng(20).uniform(.1,.2,(12,17,3)).astype(np.float32)
        old_gain=np.array([old.r_gain/1024,1,old.b_gain/1024])
        new_gain=np.array([new.r_gain/1024,1,new.b_gain/1024])
        source=encode_srgb((scene*old_gain)@np.array(old.ccm).T)
        settings=RetuneSettings((old.r_gain,old.b_gain),(new.r_gain,new.b_gain),old.ccm,new.ccm)
        expected=encode_srgb((scene*new_gain)@np.array(new.ccm).T)
        np.testing.assert_allclose(retune_screenshot(source,settings),expected,atol=2e-6)
        settings=RetuneSettings((old.r_gain,old.b_gain),(old.r_gain,old.b_gain),old.ccm,new.ccm)
        self.assertFalse(settings.is_identity)
        self.assertGreater(float(np.max(np.abs(retune_screenshot(source,settings)-source))),.001)
        same=RetuneSettings(settings.current,settings.current,old.ccm,old.ccm)
        np.testing.assert_array_equal(retune_screenshot(source,same),source)

    def test_unsafe_interpolated_matrix_is_rejected(self):
        # Both endpoints are invertible, but their midpoint is singular.
        a=CalibrationPoint(3000,1000,3000,np.eye(3))
        b=CalibrationPoint(6000,3000,1000,np.diag([-1,-1,1]))
        with self.assertRaises(ValueError):CalibrationTable((a,b)).lookup(np.sqrt(3e6),np.sqrt(3e6))


class LinkedWorkspaceTests(unittest.TestCase):
    setUp=previous.RetuneWorkspaceTests.setUp
    tearDown=previous.RetuneWorkspaceTests.tearDown
    wait_preview=previous.RetuneWorkspaceTests.wait_preview

    def set_gains(self,group,gains):
        for v,value in zip(self.panel.gains[group],gains):v.set(str(value))

    def test_auto_updates_draft_not_image_and_original_never_overwritten(self):
        p=self.panel;revision=p.revision;old=p.output.copy();original=p.matrix_editor.matrix().copy()
        self.assertEqual(p.ccm_source.get(),AUTO)
        self.set_gains('target',(3002,1703));self.root.update()
        np.testing.assert_array_equal(p.target_editor.matrix(),p.table.points[-1].ccm)
        np.testing.assert_array_equal(p.matrix_editor.matrix(),original)
        np.testing.assert_array_equal(p.output,old);self.assertEqual(p.revision,revision)
        self.assertTrue(all(str(entry.cget('state'))=='readonly' for entry in p.target_editor.entries))
        p.apply();self.wait_preview()
        self.assertFalse(p.is_dirty())
        np.testing.assert_allclose(p.output,retune_screenshot(p.source,p.applied_settings))
        p.set_table(CalibrationTable(p.table.points,'另一个设备'))
        self.assertTrue(p.is_dirty());np.testing.assert_array_equal(p.matrix_editor.matrix(),original)
        with mock.patch('isp_tool.ui.awb_retune_workspace.filedialog.asksaveasfilename') as dialog:
            p.export();dialog.assert_not_called()

    def test_original_estimate_restore_and_same_gain_warning(self):
        p=self.panel
        self.set_gains('current',(2667,2010));self.set_gains('target',(2667,2010));self.root.update()
        self.assertIn('CCM 不同',p.link_info.get())
        p.apply();self.wait_preview();self.assertFalse(np.array_equal(p.source,p.output))
        p.estimate_original();self.root.update()
        self.assertIn('估算',p.original_info.get())
        np.testing.assert_array_equal(p.matrix_editor.matrix(),p.table.points[3].ccm)
        p.apply();self.wait_preview();np.testing.assert_array_equal(p.source,p.output)
        self.set_gains('target',(3002,1703));self.root.update();p.apply();self.wait_preview()
        self.assertFalse(np.array_equal(p.source,p.output))
        p.reset_target();self.assertEqual(p.ccm_source.get(),SAME)
        p.apply();self.wait_preview();np.testing.assert_array_equal(p.source,p.output)

    def test_manual_draft_survives_auto_and_format_toggles(self):
        from isp_tool.ui.widgets.ccm_matrix_editor import FLOAT,FIXED
        p=self.panel;p.ccm_source.set(MANUAL);self.root.update()
        p.target_editor.variables[0].set('2000')
        manual=p.target_editor.matrix().copy();revision=p.revision
        self.set_gains('target',(3002,1703));self.root.update()
        np.testing.assert_array_equal(p.target_editor.matrix(),manual)
        p.ccm_source.set(AUTO);self.root.update()
        p.format.set(FLOAT);self.root.update();p.format.set(FIXED);self.root.update()
        self.assertEqual(p.revision,revision)
        p.ccm_source.set(MANUAL);self.root.update()
        np.testing.assert_array_equal(p.target_editor.matrix(),manual)
        p.target_editor.variables[0].set('-')
        p.ccm_source.set(AUTO);self.root.update()
        np.testing.assert_array_equal(p.target_editor.matrix(),p.table.points[-1].ccm)
        p.ccm_source.set(MANUAL);self.root.update()
        self.assertEqual(p.target_editor.variables[0].get(),'-')
        p.apply();self.assertEqual(p.revision,revision)

    def test_invalid_auto_draft_keeps_last_matrix_without_processing(self):
        p=self.panel;revision=p.revision;last=p.target_editor.matrix().copy()
        p.gains['target'][0].set('-');self.root.update()
        self.assertIn('待有效输入',p.link_info.get())
        np.testing.assert_array_equal(last,p.target_editor.matrix())
        p.apply();self.assertEqual(p.revision,revision)
        self.assertTrue(p.error.get())

    def test_table_dialog_transaction_crud_json_and_cancel(self):
        p=self.panel;original=p.table;revision=p.revision
        p.open_table();dialog=p.table_dialog
        self.root.update();self.assertEqual(len(dialog.points),5)
        for variable,value in zip(dialog.fields,('7000','3300','1600')):variable.set(value)
        dialog.add_point();self.assertEqual(len(dialog.points),6)
        dialog.delete_point();self.assertEqual(len(dialog.points),5)
        dialog.selected=0;dialog.show_point()
        dialog.fields[0].set('2400');dialog.update_point()
        self.assertEqual(dialog.points[0].cct,2400);self.assertEqual(p.table,original)
        # Invalid duplicate must not alter the draft table.
        dialog.fields[0].set('3054');dialog.update_point()
        self.assertTrue(dialog.error.get());self.assertEqual(len(dialog.points),5)
        dialog.show_point()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'calibration.json'
            with mock.patch('isp_tool.ui.awb_ccm_table_dialog.filedialog.asksaveasfilename',return_value=str(path)):
                dialog.save()
            payload=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(payload['ccm_encoding'],'float')
            with mock.patch('isp_tool.ui.awb_ccm_table_dialog.messagebox.askyesno',return_value=True):dialog.reset()
            self.assertEqual(dialog.points[0].cct,2300)
            with mock.patch('isp_tool.ui.awb_ccm_table_dialog.filedialog.askopenfilename',return_value=str(path)):
                dialog.load()
            self.assertEqual(dialog.points[0].cct,2400)
        dialog.accept();self.assertEqual(p.table.points[0].cct,2400)
        self.assertEqual(p.revision,revision);self.assertTrue(p.is_dirty())
        p.open_table();dialog=p.table_dialog
        dialog.fields[0].set('2450');dialog.update_point()
        with mock.patch('isp_tool.ui.awb_ccm_table_dialog.messagebox.askyesno',return_value=True):dialog.close()
        self.assertEqual(p.table.points[0].cct,2400)


if __name__=='__main__':unittest.main()
