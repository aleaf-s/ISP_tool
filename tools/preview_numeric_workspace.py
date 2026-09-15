"""Open the real workspace with synthetic data for V0.4.42 visual QA."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from isp_tool.ui.app import ISPApplication
from isp_tool.ui.dpi import enable_process_dpi_awareness

enable_process_dpi_awareness()
root = tk.Tk()
app = ISPApplication(root)
root.title("V0.4.42 Numeric Workspace · Synthetic QA")


def ready():
    if not app.results:
        root.after(50, ready)
        return
    index = next(i for i, m in enumerate(app.pipeline.modules) if m.module_id == "white_balance")
    app.pipeline_list.selection_clear(0, "end")
    app.pipeline_list.selection_set(index)
    app._on_module_select()


root.after(50, ready)
root.mainloop()
