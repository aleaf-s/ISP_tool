"""TXT export routing, HSV picking and CLUT editing without Return."""
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from isp_tool.grading.clut import HSGrid
from isp_tool.grading.hisi_clut import read_words
from isp_tool.grading.ca import load_ca_text
from tests import test_v0444


class CLUTInteractionTests(TestCase):
    setUp=test_v0444.WorkspaceTests.setUp
    tearDown=test_v0444.WorkspaceTests.tearDown
    wait_preview=test_v0444.WorkspaceTests.wait_preview

    def editor(self):
        p=self.panel;p.method.set('CLUT 调色');p.switch_method();self.wait_preview()
        return p.clut_editor

    def test_txt_routes_write_real_device_tables(self):
        p=self.panel;self.editor()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'clut.txt'
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(path)) as dialog:
                p.export_parameter_txt()
                self.assertEqual(dialog.call_args.kwargs['defaultextension'],'.txt')
            until=time.monotonic()+8
            while p.io_future is not None and time.monotonic()<until:
                self.root.update();time.sleep(.01)
            self.assertIsNone(p.io_future)
            self.assertEqual(len(read_words(path)),5508)
            p.method.set('CA 调色');p.switch_method();self.wait_preview()
            path=Path(folder)/'ca.txt'
            with mock.patch('isp_tool.ui.grading_workspace.filedialog.asksaveasfilename',return_value=str(path)) as dialog:
                p.export_parameter_txt()
                self.assertEqual(dialog.call_args.kwargs['filetypes'],[('CA TXT','*.txt')])
            self.assertEqual(load_ca_text(path).values,(1024,)*256)

    def test_pick_shows_hsv_and_selects_delta_table(self):
        p=self.panel;e=self.editor()
        with mock.patch.object(p,'open_clut_window'):p.pick_clut_at(20,20)
        self.root.update_idletasks()
        self.assertEqual(e.notebook.tab(e.notebook.select(),'text'),'Delta Hue')
        text=' '.join(e.samples.itemcget(i,'text') for i in e.samples.find_all() if e.samples.type(i)=='text')
        self.assertIn('HSV',text);self.assertIn('H 8.6°',text)
        self.assertIn('S 0.875',text);self.assertIn('V 0.8',text);self.assertNotIn('RGB',text)
        self.assertTrue(e.tables['dh'].find_withtag('selected-node'))
        e.state.tab='Delta Sat'
        with mock.patch.object(p,'open_clut_window'):p.pick_clut_at(20,20)
        self.assertEqual(e.notebook.tab(e.notebook.select(),'text'),'Delta Sat')

    def test_click_next_cell_and_tab_commit_without_applying(self):
        p=self.panel;e=self.editor();revision=p.revision
        e.open_inline('dh');e.variables[0].set('12.5')
        canvas=e.tables['dh']
        event=SimpleNamespace(x=5.5*e.cw-canvas.canvasx(0),y=2.5*e.ch-canvas.canvasy(0),state=0)
        e.table_press(event,'dh')
        self.assertEqual(e.state.grid.dh[4],12.5);self.assertEqual(e.state.selected,(1,4))
        e.open_inline('ds');e.variables[1].set('.25');e.advance_inline('ds',1)
        self.assertEqual(e.state.grid.ds[13],.25);self.assertEqual(e.state.selected,(1,5))
        self.assertEqual(e.state.applied_grid,HSGrid());self.assertEqual(p.revision,revision)
        e.variables[1].set('-');e.advance_inline('ds',1)
        self.assertEqual(e.state.selected,(1,5));self.assertTrue(p.error.get())
        e.variables[1].set('.1')
        self.assertTrue(p.apply_clut_parameters());self.wait_preview()
        self.assertEqual(e.state.applied_grid.ds[14],.1)
