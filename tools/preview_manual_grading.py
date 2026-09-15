"""Synthetic, disposable desktop QA; does not open user images."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tkinter as tk
import numpy as np
from isp_tool.ui.dpi import enable_process_dpi_awareness
from isp_tool.ui.theme import configure_theme
from isp_tool.ui.grading_workspace import GradingWorkspace
from isp_tool.grading.image_io import ColorDocument
from isp_tool.grading.model import ColorPoint,GradeHistory
enable_process_dpi_awareness()
root=tk.Tk();root.title('Manual Colour Grading · Synthetic QA');root.geometry('1400x850')
configure_theme(root)
panel=GradingWorkspace(root,root.destroy);panel.pack(fill='both',expand=True)
y,x=np.mgrid[0:600,0:800].astype(np.float32)
rgb=np.stack((.1+.8*x/799,.1+.7*y/599,.8-.6*x/799),axis=-1)
rgb[120:300,150:350]=(.8,.2,.1)
history=GradeHistory();history.replace([ColorPoint((.8,.2,.1),(.6,.4,.15))])
panel.documents=[ColorDocument('Synthetic colour scene',rgb,None,8,'sRGB · synthetic')]
panel.history=history
panel.selected=0
panel.refresh_points()
panel.select_document(0)
root.mainloop()
