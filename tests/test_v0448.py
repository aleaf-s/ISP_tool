"""AWB simulation: persistent accepted tables and compact parameter groups."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from isp_tool.awb_calibration_store import CalibrationStore
from isp_tool.awb_ccm_table import CalibrationPoint, CalibrationTable
from isp_tool.ui.awb_retune_workspace import AWBRetuneWorkspace, SAME, MANUAL
from isp_tool.ui.widgets.tool_selector import ToolSelector
from tests import test_v0446 as previous


class CalibrationStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'config'/'awb_ccm_calibration.json'
        self.store = CalibrationStore(self.path)

    def test_missing_uses_defaults_without_writing(self):
        self.assertEqual(self.store.load(), CalibrationTable.default())
        self.assertFalse(self.path.exists())

    def test_save_load_name_points_and_full_precision(self):
        base = CalibrationTable.default()
        matrix = np.array(base.points[-1].ccm)
        matrix[0, 0] = 1.765432109876
        extra = CalibrationPoint(7000, 3300, 1600, matrix)
        table = CalibrationTable(base.points+(extra,), '我的相机')
        self.store.save(table)
        self.assertEqual(CalibrationStore(self.path).load(), table)
        self.assertEqual(json.loads(self.path.read_text('utf-8'))['ccm_encoding'], 'float')
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_failed_atomic_replace_keeps_previous_file(self):
        self.store.save(CalibrationTable.default())
        before = self.path.read_bytes()
        table = CalibrationTable(CalibrationTable.default().points, 'new')
        with mock.patch('isp_tool.awb_calibration_store.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(OSError):
                self.store.save(table)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_malformed_schema_and_large_files_preserved(self):
        self.path.parent.mkdir()
        for content in ('{broken', '{}', 'x'*(1024*1024+1)):
            self.path.write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError):
                self.store.load()
            self.assertEqual(self.path.read_text('utf-8'), content)

    def test_storage_follows_user_preferences_directory(self):
        preferences = self.path.parent/'ui_preferences.json'
        with mock.patch.dict('os.environ', {'ISP_TOOL_PREFERENCES_PATH': str(preferences)}):
            self.assertEqual(CalibrationStore().path, self.path)


class SimulationWorkspaceTests(unittest.TestCase):
    setUp = previous.RetuneWorkspaceTests.setUp
    tearDown = previous.RetuneWorkspaceTests.tearDown
    wait_preview = previous.RetuneWorkspaceTests.wait_preview

    def test_accept_restores_on_reopen_without_reprocessing(self):
        p = self.panel
        revision, output = p.revision, p.output.copy()
        p.open_table()
        dialog = p.table_dialog
        dialog.fields[0].set('2400')
        dialog.update_point()
        dialog.name.set('已标定设备')
        self.assertFalse(self.calibration_path.exists())
        dialog.accept()
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(p.table.points[0].cct, 2400)
        self.assertEqual(p.revision, revision)
        np.testing.assert_array_equal(p.output, output)
        restored = AWBRetuneWorkspace(self.root, self.tool, lambda _: None,
                                      calibration_path=self.calibration_path)
        try:
            self.assertEqual(restored.table, p.table)
            self.assertEqual(restored.table.name, '已标定设备')
            self.assertEqual(restored.revision, 0)
        finally:
            restored.destroy()

    def test_failed_save_keeps_dialog_drafts_active_table_and_disk(self):
        p = self.panel
        p.set_table(p.table)
        before = self.calibration_path.read_bytes()
        table = p.table
        p.open_table()
        dialog = p.table_dialog
        dialog.fields[0].set('2400');dialog.update_point()
        with mock.patch.object(p.calibration_store, 'save', side_effect=PermissionError('locked')):
            dialog.accept()
        self.assertTrue(dialog.winfo_exists())
        self.assertIn('保存失败', dialog.error.get())
        self.assertEqual(dialog.points[0].cct, 2400)
        self.assertEqual(p.table, table)
        self.assertEqual(self.calibration_path.read_bytes(), before)

    def test_cancel_never_saves(self):
        p = self.panel
        p.open_table()
        dialog = p.table_dialog
        dialog.fields[0].set('2400');dialog.update_point()
        with mock.patch('isp_tool.ui.awb_ccm_table_dialog.messagebox.askyesno', return_value=True):
            dialog.close()
        self.assertFalse(self.calibration_path.exists())
        self.assertEqual(p.table, CalibrationTable.default())

    def test_corrupt_file_warns_without_overwriting(self):
        self.calibration_path.write_text('{broken', encoding='utf-8')
        restored = AWBRetuneWorkspace(self.root, self.tool, lambda _: None,
                                      calibration_path=self.calibration_path)
        try:
            self.assertEqual(restored.table, CalibrationTable.default())
            self.assertIn('读取失败', restored.storage_warning.get())
            restored.apply()
            self.assertIn('读取失败', restored.storage_warning.get())
            self.assertEqual(self.calibration_path.read_text('utf-8'), '{broken')
            restored.set_table(CalibrationTable.default())
            self.assertEqual(restored.storage_warning.get(), '')
        finally:
            restored.destroy()

    def test_groups_tool_name_and_pinned_actions(self):
        p = self.panel
        self.assertEqual(ToolSelector.LABELS['awb_retune'], 'AWB 仿真')
        self.assertEqual(p.parameter_groups['current'].cget('text'), '原参数')
        self.assertEqual(p.parameter_groups['target'].cget('text'), '目标参数')
        self.assertIs(p.matrix_editor.master, p.parameter_groups['current'])
        self.assertIs(p.target_editor.master, p.parameter_groups['target'])
        self.assertIs(p.source_combo.master, p.parameter_groups['target'])
        self.assertEqual(p.action_footer.pack_info()['side'], 'bottom')
        self.assertEqual(p.action_footer.master, p.parameter_canvas.master.master)
        for group in ('current', 'target'):
            group_vars = {str(v) for v in p.gains[group]}
            descendants = []
            def collect(widget):
                descendants.append(widget)
                for child in widget.winfo_children(): collect(child)
            collect(p.parameter_groups[group])
            bound_vars = {str(w.cget('textvariable')) for w in descendants if 'textvariable' in w.keys()}
            self.assertTrue(group_vars.issubset(bound_vars))

    def test_warning_not_duplicated_and_normal_text_hidden(self):
        p = self.panel
        p.estimate_original()
        self.root.update()
        self.assertEqual(p.error.get(), '')
        self.assertIn('估算', p.original_info.get())
        warning = p.table.lookup(1024, 1024).warning
        self.assertTrue(warning)
        combined = p.original_info.get()+'\n'+p.link_info.get()+'\n'+p.error.get()
        self.assertEqual(combined.count(warning), 1)
        p.ccm_source.set(SAME);self.root.update()
        self.assertEqual(p.link_info.get(), '')
        self.assertEqual(p.link_label.master.winfo_reqheight(), 1)
        p.apply();self.wait_preview()
        self.assertEqual(p.dirty_label.get(), '')
        p.ccm_source.set(MANUAL);self.root.update()
        matrix = p.target_editor.matrix();matrix[0, 0] += .0001
        p.target_editor.set_matrix(matrix)
        self.root.update()
        self.assertIn('量化近似', p.target_editor.message_var.get())
        self.assertEqual(p.target_editor.message_label.winfo_manager(), '')
        p.target_editor.variables[0].set('bad')
        p.apply();self.root.update()
        self.assertTrue(p.error.get())
        self.assertEqual(p.target_editor.message_label.winfo_manager(), 'pack')


if __name__ == '__main__':
    unittest.main()
