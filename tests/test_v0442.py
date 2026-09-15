import copy
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest import mock
import numpy as np

from isp_tool.ccm_encoding import decode_ccm, encode_ccm, FIXED_MAX
from isp_tool.models import ParameterSpec
from isp_tool.ui.widgets.parameter_control import ParameterControl
from isp_tool.ui.widgets.ccm_matrix_editor import CCMMatrixEditor, FLOAT, FIXED
from isp_tool.ui.theme import COLORS, configure_theme


class EncodingTests(unittest.TestCase):
    def test_every_13_bit_code_round_trips(self):
        for code in range(8192):
            self.assertEqual(encode_ccm(decode_ccm(code)), code)

    def test_boundaries_and_even_ties(self):
        for coefficient, code in [(0, 0), (1, 1024), (2, 2048), (-.5, 7680), (-1, 7168), (-4, 4096), (-1/1024, 8191), (FIXED_MAX, 4095), (-4095/1024, 4097)]:
            self.assertEqual(encode_ccm(coefficient), code)
            self.assertEqual(decode_ccm(code), coefficient)
        self.assertEqual(encode_ccm(.5/1024), 0)
        self.assertEqual(encode_ccm(1.5/1024), 2)
        self.assertEqual(encode_ccm(-1.5/1024), 8190)
        for value in (4, -4.001, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                encode_ccm(value)
        for code in (-1, 8192, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                decode_ccm(code)


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        configure_theme(self.root)

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_partial_numeric_input_and_precise_commit(self):
        calls = []
        control = ParameterControl(self.root, ParameterSpec("x", "X", "float", 1, -4, 4, .001), 1, calls.append)
        self.assertEqual(int(control.entry.cget("width")), 10)
        self.assertFalse(control.entry.pack_info()["expand"])
        for text in ("", "-", ".", "2e", "nan", "5"):
            control.entry_var.set(text)
            self.assertEqual(calls, [])
            control._entry_commit()
            self.assertEqual(control.value(), 1)
            self.assertEqual(control.entry_var.get(), text)
            self.assertTrue(control.error_var.get())
        control.entry_var.set("1.234567890123456")
        control._entry_commit()
        control._entry_commit()
        self.assertEqual(calls, [True])
        self.assertEqual(control.value(), 1.234567890123456)

    def test_integer_reset_and_key_increment(self):
        c = ParameterControl(self.root, ParameterSpec("x", "X", "int", 4, 0, 100, 2), 4, lambda _: None)
        c.entry_var.set("1.5")
        c._entry_commit()
        self.assertEqual(c.value(), 4)
        c.entry_var.set("4")
        c._key_step(SimpleNamespace(state=1), 1)
        self.assertEqual(c.value(), 24)
        c.reset()
        self.assertEqual(c.value(), 4)

    def test_display_switch_preserves_precision_and_unedited_cells(self):
        matrix = np.eye(3) * 1.12345678912345
        e = CCMMatrixEditor(self.root, matrix)
        self.assertFalse(e.entries[0].master.pack_info()["expand"])
        self.assertTrue(all(8 <= int(cell.cget("width")) <= 12 for cell in e.entries))
        self.assertTrue(e.set_mode(FIXED))
        self.assertTrue(e.message_var.get())
        np.testing.assert_array_equal(e.matrix(), matrix)
        self.assertTrue(e.set_mode(FLOAT))
        np.testing.assert_array_equal(e.matrix(), matrix)
        e.variables[1].set("-0.333333333333")
        self.assertTrue(e.set_mode(FIXED))
        e.variables[0].set("2048")
        result = e.matrix()
        self.assertEqual(result[0, 0], 2)
        self.assertEqual(result[0, 1], -.333333333333)
        self.assertEqual(result[1, 1], matrix[1, 1])

    def test_invalid_draft_not_lost_on_format_switch(self):
        e = CCMMatrixEditor(self.root, np.eye(3))
        e.variables[0].set("-")
        self.assertFalse(e.set_mode(FIXED))
        self.assertEqual(e.variables[0].get(), "-")
        e.variables[0].set("4")
        self.assertFalse(e.set_mode(FIXED))
        self.assertEqual(e.matrix()[0, 0], 4)
        e.variables[0].set("1")
        self.assertTrue(e.set_mode(FIXED))
        for text in ("1024.5", "8192", "-1", ""):
            e.variables[0].set(text)
            with self.assertRaises(ValueError):
                e.matrix()

    def test_shared_format_preference_and_draft_restore(self):
        preference = tk.StringVar(self.root, value=FLOAT)
        a, b = [CCMMatrixEditor(self.root, np.eye(3), preference) for _ in range(2)]
        a.variables[0].set("1.7")
        a.mode_var.set(FIXED)
        a._mode_selected()
        self.assertEqual(b.mode, FIXED)
        snapshot = a.snapshot()
        a.destroy()
        c = CCMMatrixEditor(self.root, np.eye(3), preference)
        c.restore(snapshot)
        self.assertEqual(c.matrix()[0, 0], 1.7)
        preference.set(FLOAT)
        self.assertEqual(c.mode, FLOAT)

    def test_light_theme_states(self):
        style = ttk.Style(self.root)
        self.assertGreater(sum(self.root.winfo_rgb(COLORS["panel"])), sum(self.root.winfo_rgb(COLORS["foreground"])))
        for state in ((), ("active",), ("focus",), ("disabled",)):
            self.assertTrue(style.lookup("TCombobox", "arrowcolor", state))
        self.assertTrue(style.lookup("Invalid.Parameter.TEntry", "bordercolor"))

    def test_application_matrix_is_draft_until_correct_and_survives_rebuild(self):
        from isp_tool.ui.app import ISPApplication
        app = ISPApplication(self.root)
        try:
            module = app._ccm_module()
            index = app.pipeline.modules.index(module)
            app.pipeline_list.selection_clear(0, "end")
            app.pipeline_list.selection_set(index)
            app._on_module_select()
            original = copy.deepcopy(module.parameters)
            with mock.patch.object(app, "schedule_process") as process:
                app.ccm_editor.variables[0].set("1.23456789")
                app.ccm_format_var.set(FIXED)
                app._build_parameter_editor(module)
                self.assertEqual(app.ccm_editor.matrix()[0, 0], 1.23456789)
                self.assertEqual(module.parameters, original)
                process.assert_not_called()
                app.ccm_editor.variables[0].set("1776")
                app._apply_ccm_draft()
                self.assertEqual(module.parameters["m00"], 1776/1024)
                self.assertEqual(process.call_count, 1)
                app._apply_ccm_draft()
                self.assertEqual(process.call_count, 1)
            app.open_calibration_workspace()
            panel = app.calibration_workspace.auto_panel
            self.assertIsInstance(panel.ccm_editor, CCMMatrixEditor)
            self.assertIs(panel.ccm_editor.preference, app.ccm_format_var)
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
