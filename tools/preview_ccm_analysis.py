"""Interactive UI-only QA fixture (synthetic chart; no user files changed).

Run from the project root: python tools/preview_ccm_analysis.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tkinter as tk
from tkinter import ttk
import numpy as np

from isp_tool.calibration.ccm_analysis import evaluate_matrix
from isp_tool.calibration.colorchecker import colorchecker_reference
from isp_tool.ui.ccm_analysis_window import CCMAnalysisWindow
from isp_tool.ui.theme import configure_theme


root = tk.Tk()
root.title("CCM V0.4.41 · UI QA (Synthetic)")
root.geometry("440x180")
configure_theme(root, 1.25)
names, reference = colorchecker_reference()
matrix = np.array([[1.12, -.08, -.04], [-.03, 1.08, -.05], [-.02, -.07, 1.09]])
measurements = evaluate_matrix({"patches": [dict(
    patch_id=i+1, name=name, measured_rgb=rgb.tolist(), reference_rgb=rgb.tolist(),
    diagnostics={"valid": True},
) for i, (name, rgb) in enumerate(zip(names, reference))]}, matrix)
window = CCMAnalysisWindow(root)
window.withdraw()
window.on_patch_selected = lambda n: window.focus_patch(n)
ticks = 0
status = tk.StringVar()


def heartbeat():
    global ticks
    ticks += 1
    status.set(f"UI heartbeat: {ticks} · synthetic samples only")
    root.after(100, heartbeat)


def show():
    window.set_result(measurements)
    window.deiconify()
    window.lift()


ttk.Button(root, text="Color Analysis (double-click test)", command=show).pack(padx=20, pady=20)
ttk.Label(root, textvariable=status).pack()
heartbeat()
root.mainloop()
