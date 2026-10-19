"""Embedded manual grading workspace: source picking and final comparison."""
import colorsys
import copy
import math
from dataclasses import replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from uuid import uuid4
import cv2
import numpy as np
from PIL import Image
from ..grading.model import GradeHistory, ColorPoint, build_lut, apply_lut, raster8, sample_original
from ..grading.image_io import read_color_image, export_color_image, export_processed_image
from ..grading.clut import (build_clut, apply_clut,
                           locate_rgb_node,neighbor_weights,sample_hs_field)
from ..grading.ca import CACurve, apply_ca, load_ca_text, export_ca_text
from ..grading.hsv_grid import HSVGrid, VALUES, load_hsv, export_hsv, locate as locate_hsv, influence as hsv_influence
from ..grading.session import GradingState, processing_key, preview_lut
from .theme import COLORS
from .number_format import format_number
from .widgets.tooltip import Tooltip
from .widgets.tool_selector import ToolSelector
from .widgets.comparison_view import ComparisonViewMixin
from .widgets.clut_editor import CLUTEditor
from .widgets.ca_editor import CAEditor


class GradingWorkspace(ComparisonViewMixin, ttk.Frame):
    def __init__(self,parent,on_back,tool_variable=None,on_tool=None):
        super().__init__(parent)
        self.on_back=on_back
        self._empty_history=GradeHistory()
        self.states={}
        self._influence_cache=None
        self._active_document=None
        self._editor_epoch=0
        self._point_rows={}
        self.documents=[]
        self.index=-1
        self.selected=-1
        self.revision=0
        self.future=None
        self.io_future=None
        self.executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='manual-colour')
        self._timers=set()
        self.closed=False
        self.source=self.output=None
        self.source_pil=self.output_pil=None
        self._photos=[]
        self.zoom=1.0
        self.offset=[0.,0.]
        self.fit=True
        self.divider=.5
        self.drag=None
        self.hold_original=False
        self._render_timer=None
        self._shown_revision=-1
        self.status=tk.StringVar(self,value='导入 PNG / JPEG / TIFF · sRGB')
        bar=ttk.Frame(self,padding=8)
        bar.pack(fill='x')
        self.tool_variable=tool_variable if tool_variable is not None else tk.StringVar(self,value='grading')
        self.tool_selector=ToolSelector(bar,self.tool_variable,on_tool or (lambda key:on_back() if key!='grading' else None))
        self.tool_selector.pack(side='left',padx=(0,12))
        ttk.Button(bar,text='导入彩色图像',command=self.open_images,style='Primary.TButton').pack(side='left')
        self.file_combo=ttk.Combobox(bar,state='readonly',width=28)
        self.file_combo.pack(side='left',padx=5)
        self.file_combo.bind('<<ComboboxSelected>>',lambda e:self.select_document(self.file_combo.current()))
        Tooltip(self.file_combo,lambda:self.document.path if self.document else '')
        ttk.Button(bar,text='移除',command=self.remove_document,width=5).pack(side='left')
        self.export_menu=tk.Menu(self,tearoff=False)
        self.export_menu.add_command(label='导出图像…',command=self.export)
        self.export_menu.add_command(label='导出参数 TXT…',command=self.export_parameter_txt,state='disabled')
        self.export_button=ttk.Menubutton(bar,text='导出 ▾',menu=self.export_menu)
        self.export_button.pack(side='right')
        body=ttk.Frame(self,padding=(8,0,8,0))
        body.pack(fill='both',expand=True)
        right_host=ttk.Frame(body,padding=(12,0,0,0))
        right_host.pack(side='right',fill='y')
        self.parameter_canvas=tk.Canvas(right_host,width=315,highlightthickness=0,bg=COLORS['panel'])
        scroll=ttk.Scrollbar(right_host,command=self.parameter_canvas.yview)
        scroll.pack(side='right',fill='y')
        self.parameter_canvas.configure(yscrollcommand=scroll.set)
        self.parameter_canvas.pack(side='left',fill='both',expand=True)
        right=ttk.Frame(self.parameter_canvas)
        parameter_window=self.parameter_canvas.create_window(0,0,window=right,anchor='nw')
        def size_parameters(event,content=right):
            # Use the actual font/control request, not hard-coded physical
            # pixels; Windows 150/200% DPI otherwise clips the third column.
            self.parameter_canvas.configure(width=max(315,content.winfo_reqwidth()),
                                            scrollregion=self.parameter_canvas.bbox('all'))
        right.bind('<Configure>',size_parameters)
        self.parameter_canvas.bind('<Configure>',lambda e:self.parameter_canvas.itemconfigure(parameter_window,width=e.width))
        left=ttk.Frame(body)
        left.pack(side='left',fill='both',expand=True)
        tools=ttk.Frame(left)
        tools.pack(fill='x',pady=(0,6))
        self.pick=tk.BooleanVar(self,value=False)
        self.pick_button=ttk.Checkbutton(tools,text='取色（原图 5×5）',variable=self.pick)
        self.pick_button.pack(side='left')
        self.mode=tk.StringVar(self,value='滑动对比')
        mode=ttk.Combobox(tools,textvariable=self.mode,values=('左右并排','滑动对比'),state='readonly',width=10)
        mode.pack(side='left',padx=6)
        mode.bind('<<ComboboxSelected>>',lambda e:self.fit_image())
        view_tools=ttk.Frame(left)
        view_tools.pack(fill='x',pady=(0,6))
        ttk.Button(view_tools,text='适应窗口',command=self.fit_image).pack(side='left')
        original=ttk.Button(view_tools,text='按住看原图')
        original.pack(side='left',padx=6)
        original.bind('<ButtonPress-1>',lambda e:self.show_original(True))
        original.bind('<ButtonRelease-1>',lambda e:self.show_original(False))
        original.bind('<Leave>',lambda e:self.show_original(False))
        self.enabled=tk.BooleanVar(self,value=True)
        ttk.Checkbutton(view_tools,text='启用调色',variable=self.enabled,command=self.toggle_enabled).pack(side='left')
        self.canvas=tk.Canvas(left,bg='#707070',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.schedule_draw())
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',lambda e:setattr(self,'drag',None))
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Motion>',self.hover)
        self.editor_host=right
        self.method=tk.StringVar(self,value='取色调色')
        method=ttk.Combobox(right,textvariable=self.method,values=('取色调色','HSV 调色','CA 调色'),state='readonly',width=16)
        method.pack(anchor='w',pady=(0,6))
        method.bind('<<ComboboxSelected>>',self.switch_method)
        self.point_panel=ttk.Frame(right);self.point_panel.pack(fill='x')
        right=self.point_panel
        ttk.Label(right,text='颜色控制点',style='Title.TLabel').pack(anchor='w')
        self.point_list=ttk.Treeview(right,columns=('origin',),show='tree headings',height=7,selectmode='browse')
        self.point_list.heading('#0',text='名称')
        self.point_list.column('#0',width=140,minwidth=90)
        self.point_list.heading('origin',text='来源')
        self.point_list.column('origin',width=170,minwidth=90)
        self.point_list.pack(fill='x',pady=6)
        self.point_list.bind('<<TreeviewSelect>>',self.select_point)
        self.point_list.bind('<Double-1>',self.rename_point)
        self.point_list.bind('<Button-3>',self.point_menu)
        Tooltip(self.point_list,self.point_details)
        self.point_context=tk.Menu(self,tearoff=False)
        action=ttk.Frame(right)
        action.pack(fill='x')
        ttk.Button(action,text='更多 ▾',command=self.show_point_menu,width=7).pack(side='left')
        ttk.Button(action,text='重置当前',command=self.reset_point).pack(side='left',padx=5)
        ttk.Button(action,text='重置本图',command=self.reset_all).pack(side='left')
        self.original_label=ttk.Label(right,text='Original · 未取色',justify='left')
        self.original_label.pack(anchor='w',pady=(12,3))
        self.swatches=tk.Canvas(right,width=235,height=25,highlightthickness=0)
        self.swatches.pack(anchor='w',pady=3)
        self.values={}
        for group,names in (('RGB',('R','G','B')),('HSV',('H°','S 0–1','V 0–1'))):
            ttk.Label(right,text='Target '+group).pack(anchor='w',pady=(8,2))
            row=ttk.Frame(right)
            row.pack(anchor='w')
            variables=[]
            for name in names:
                cell=ttk.Frame(row)
                cell.pack(side='left',padx=(0,5))
                ttk.Label(cell,text=name).pack(anchor='w')
                variable=tk.StringVar(self,value='0')
                entry=ttk.Entry(cell,textvariable=variable,width=7,justify='right',style='Parameter.TEntry')
                entry.pack()
                entry.bind('<Return>',lambda e,g=group:self.commit_target(g))
                entry.bind('<FocusOut>',lambda e,g=group:self.defer_commit(lambda:self.commit_target(g)))
                variables.append(variable)
            self.values[group]=variables
        self._rendered={}
        self.radius=tk.StringVar(self,value='25')
        self.strength=tk.StringVar(self,value='100')
        for label,var,tip in (('影响范围',self.radius,'5…100 · Lab distance'),('强度 %',self.strength,'0…100')):
            row=ttk.Frame(right)
            row.pack(anchor='w',pady=(10,0))
            ttk.Label(row,text=label,width=10).pack(side='left')
            entry=ttk.Entry(row,textvariable=var,width=7,justify='right',style='Parameter.TEntry')
            entry.pack(side='left')
            Tooltip(entry,tip)
            entry.bind('<Return>',self.commit_influence)
            entry.bind('<FocusOut>',lambda e:self.defer_commit(self.commit_influence))
        self.error=tk.StringVar(self)
        self.draft_status=tk.StringVar(self)
        ttk.Label(right,textvariable=self.draft_status,style='Muted.TLabel').pack(anchor='w')
        ttk.Label(right,textvariable=self.error,style='Error.TLabel',wraplength=275).pack(fill='x',pady=8)
        history=ttk.Frame(right)
        history.pack(fill='x',pady=4)
        self.undo_button=ttk.Button(history,text='撤销',command=lambda:self.travel(False))
        self.redo_button=ttk.Button(history,text='重做',command=lambda:self.travel(True))
        self.undo_button.pack(side='left')
        self.redo_button.pack(side='left',padx=5)
        ttk.Label(self,textvariable=self.status,style='Muted.TLabel',padding=8).pack(fill='x')
        def bind_scroll(widget):
            if widget is not self.point_list:
                widget.bind('<MouseWheel>',self.scroll_parameters)
            for child in widget.winfo_children():bind_scroll(child)
        bind_scroll(right)
        self.parameter_canvas.bind('<MouseWheel>',self.scroll_parameters)
        self.refresh_points()
        self._draft_traces=[]
        for var in [v for vs in self.values.values() for v in vs]+[self.radius,self.strength]:
            self._draft_traces.append((var,var.trace_add('write',self.update_draft_status)))
        self.clut_status=tk.StringVar(self,value='已应用')
        self.clut_panel=ttk.Frame(self.editor_host)
        ttk.Label(self.clut_panel,text='HSV',style='Title.TLabel').pack(anchor='w')
        ttk.Button(self.clut_panel,text='打开 HSV 调试窗口…',command=self.open_clut_window).pack(fill='x',pady=6)
        ttk.Label(self.clut_panel,textvariable=self.clut_status,style='Muted.TLabel').pack(anchor='w',pady=4)
        ttk.Button(self.clut_panel,text='应用',command=self.apply_clut_parameters,style='Primary.TButton').pack(fill='x',pady=5)
        ttk.Button(self.clut_panel,text='恢复到上次应用',command=self.restore_clut_applied).pack(fill='x',pady=3)
        ttk.Label(self.clut_panel,textvariable=self.error,style='Error.TLabel',wraplength=300).pack(fill='x')
        self.clut_window=tk.Toplevel(self)
        self.clut_window.withdraw()
        self.clut_window.title('HSV 调试')
        self.clut_window.resizable(True,True)
        self.clut_window.protocol('WM_DELETE_WINDOW',self.hide_clut_window)
        self.clut_editor=CLUTEditor(self.clut_window,self.clut_changed,self.error,self.update_clut_status,
                                    self.schedule_draw,self.begin_clut_pick)
        self.clut_editor.pack(fill='both',expand=True,padx=8,pady=8)
        footer=ttk.Frame(self.clut_editor.sidebar,padding=(0,12));footer.pack(fill='x')
        self.hsv_footer=footer
        actions=ttk.Frame(footer);actions.pack(fill='x',pady=(0,5))
        ttk.Button(actions,text='应用',command=self.apply_clut_parameters,style='Primary.TButton').pack(side='right')
        ttk.Button(actions,text='恢复到上次应用',command=self.restore_clut_applied).pack(side='right',padx=5)
        ttk.Label(footer,textvariable=self.clut_status,style='Muted.TLabel').pack(anchor='w')
        files=ttk.Frame(footer);files.pack(fill='x')
        ttk.Button(files,text='导入 HSV TXT…',command=self.load_hsv_file).pack(side='left',padx=(0,5))
        ttk.Button(files,text='导出 HSV TXT…',command=self.save_hsv_file).pack(side='left')
        self.clut_source=tk.StringVar(self)
        source_label=ttk.Label(footer,textvariable=self.clut_source,style='Muted.TLabel',wraplength=650)
        # Routine explanations live in tooltips, not the compact parameter sidebar.
        Tooltip(files,'图像预览为软件近似，并非海思 ISP 的实机效果。')
        self.clut_import_note=tk.StringVar(self)
        note_label=ttk.Label(footer,textvariable=self.clut_import_note,wraplength=650)
        error_label=ttk.Label(footer,textvariable=self.error,style='Error.TLabel',wraplength=650);error_label.pack(anchor='w')
        footer.bind('<Configure>',lambda e:[label.configure(wraplength=max(200,e.width-16)) for label in (source_label,note_label,error_label)])
        self.clut_editor.sidebar.update_idletasks()
        self.clut_editor.side_view.configure(width=max(340,self.clut_editor.sidebar.winfo_reqwidth()))
        sw,sh=self.winfo_screenwidth(),self.winfo_screenheight()
        width=min(round(sw*.85),max(900,self.clut_editor.cw*10+55))
        height=min(round(sh*.85),max(800,self.clut_editor.ch*30))
        self.clut_window.geometry(f'{width}x{height}')
        self.clut_window.minsize(min(width,max(540,self.clut_editor.canvas_width+40)),min(height,600))
        self.ca_status=tk.StringVar(self,value='已应用')
        self.ca_panel=ttk.Frame(self.editor_host)
        ttk.Label(self.ca_panel,text='CA',style='Title.TLabel').pack(anchor='w')
        ttk.Button(self.ca_panel,text='打开 CA 曲线窗口…',command=self.open_ca_window).pack(fill='x',pady=6)
        ttk.Label(self.ca_panel,textvariable=self.ca_status,style='Muted.TLabel').pack(anchor='w',pady=4)
        ttk.Button(self.ca_panel,text='应用',command=self.apply_ca_parameters,style='Primary.TButton').pack(fill='x',pady=5)
        ttk.Button(self.ca_panel,text='恢复到上次应用',command=self.restore_ca_applied).pack(fill='x',pady=3)
        ttk.Label(self.ca_panel,textvariable=self.error,style='Error.TLabel',wraplength=300).pack(fill='x')
        self.ca_window=tk.Toplevel(self)
        self.ca_window.withdraw()
        self.ca_window.title('CA · Chroma Adjust')
        self.ca_window.resizable(True,True)
        self.ca_window.protocol('WM_DELETE_WINDOW',self.hide_ca_window)
        self.ca_editor=CAEditor(self.ca_window,self.ca_changed,self.apply_ca_parameters,
                                self.restore_ca_applied,self.load_ca_file,self.export_ca_file,self.error,
                                self.update_ca_status)
        self.ca_editor.pack(fill='both',expand=True)
        self.ca_window.geometry(f'{min(round(sw*.82),1150)}x{min(round(sh*.8),700)}')
        self.ca_window.update_idletasks()
        self.ca_window.minsize(max(640,self.ca_editor.side.winfo_reqwidth()+320),420)
        self.bind('<Unmap>',lambda e:self.hide_clut_window() if e.widget is self else None,add='+')
        self.bind('<Unmap>',lambda e:self.hide_ca_window() if e.widget is self else None,add='+')

    def open_clut_window(self):
        if self.document is None or self.method.get()!='HSV 调色':return
        self.clut_window.title(f'HSV 调试 · {Path(self.document.path).name}')
        self.clut_window.deiconify();self.clut_window.lift()
        self.clut_window.update_idletasks()
        # Reserve a useful table viewport at the actual Tk font/DPI scale.
        # Fixed 600px minima otherwise allow the footer to crush the table.
        editor=self.clut_editor
        needed_h=editor.parameter_header.winfo_reqheight()+420
        needed_w=max(760,editor.sidebar.winfo_reqwidth()+400)
        self.clut_window.minsize(min(needed_w,self.winfo_screenwidth()-40),
                                 min(needed_h,self.winfo_screenheight()-80))

    def begin_clut_pick(self):
        if self.document is None:return
        self.hide_clut_window();self.pick.set(True)
        self.winfo_toplevel().lift()
        self.status.set('点击原图颜色定位 HSV（取原始像素 5×5，不采样叠加色）')

    def pick_clut_at(self,x,y):
        document=self.document
        if document is None or not (0<=x<document.rgb.shape[1] and 0<=y<document.rgb.shape[0]):return False
        if document.alpha is not None and document.alpha[y,x]<.1:
            self.error.set('请在非透明区域取色');return False
        color=sample_original(document.rgb,x,y)
        state=self.state_for(document).clut;state.sample_rgb=tuple(float(v) for v in color)
        if isinstance(state.grid,HSVGrid):
            index,row,column=locate_hsv(color)
            self.clut_editor.remember_draft();self.clut_editor.close_inline()
            state.slice_index=4
            self.clut_editor.show_node()
            self.clut_editor.locate_sample(row,column)
        else:self.clut_editor.locate_sample(*locate_rgb_node(color))
        self.pick.set(False);self.open_clut_window()
        return True

    def restore_clut_applied(self):
        if self.document is None or self.method.get()!='HSV 调色':return
        editor=self.clut_editor;state=self.state_for(self.document).clut
        editor._drag_grid=editor._drag_preview=None;editor.close_inline()
        state.drafts.clear();state.strength_draft=None;state.gain_draft=None;state.replace(state.applied_grid)
        state.hsv_path=state.applied_hsv_path;state.import_note='已恢复上次应用的 HSV 参数'
        editor.show_node();editor.redraw();self.error.set('');self.update_clut_status()

    def decorate_comparison_views(self,before,after):
        if self.document is None or self.method.get()!='HSV 调色' or self.hold_original:return before,after
        state=self.state_for(self.document).clut
        if not state.show_influence:return before,after
        key=(self.document.document_id,self.source.shape[:2],state.selected,state.radius,state.smoothness,
             isinstance(state.grid,HSVGrid),state.slice_index)
        if self._influence_cache is None or self._influence_cache[0]!=key:
            hsv=cv2.cvtColor(np.asarray(self.source,np.float32),cv2.COLOR_RGB2HSV)
            if isinstance(state.grid,HSVGrid):
                weight=hsv_influence(hsv,state.slice_index,*state.selected,state.radius,state.smoothness)
            else:weight=sample_hs_field(hsv,neighbor_weights(*state.selected,state.radius,state.smoothness))
            weight=np.where(hsv[...,1]>0,weight,0)
            if self.document.alpha is not None:
                weight*=cv2.resize(self.document.alpha,(self.source.shape[1],self.source.shape[0]))
            self._influence_cache=(key,Image.fromarray(np.rint(np.clip(weight,0,1)*115).astype(np.uint8)))
        ox,oy=self.offset;z=self.zoom
        mask=self._influence_cache[1].transform(before.size,Image.Transform.AFFINE,
              (1/z,0,-ox/z,0,1/z,-oy/z),resample=Image.Resampling.BILINEAR,fillcolor=0)
        tint=Image.new('RGB',before.size,(255,125,0))
        return Image.composite(tint,before,mask),Image.composite(tint,after,mask)

    def hide_clut_window(self):
        self.clut_editor.remember_draft()
        # Closing the window stores a dragged node as a draft, never applies it.
        if self.document and self.clut_editor.state is self.state_for(self.document).clut:
            self.clut_editor.wheel_release()
        self.clut_editor.close_inline()
        self.clut_window.withdraw()

    def update_clut_status(self):
        if self.document is None:self.clut_status.set('请导入图像');return
        state=self.state_for(self.document).clut
        warning='图像预览为软件近似，非海思 ISP 效果'
        if not state.grid.preview_supported:warning='第三字段未确认：仅可编辑 H/S 和导出，不能应用图像'
        elif state.grid.prefix.strip():warning+='；RGB 对记录仅保留'
        self.clut_source.set(warning)
        self.clut_import_note.set(state.import_note)
        self.clut_status.set('待应用' if state.pending() else '已应用')

    def hsv_apply_failed(self,message):
        self.error.set(message);self.clut_status.set('未应用')
        if self.clut_window.winfo_viewable():
            messagebox.showerror('HSV 未应用',message,parent=self.clut_window)
        return False

    def apply_clut_parameters(self):
        if self.document is None or self.method.get()!='HSV 调色':return False
        if not self.clut_editor.commit_all():return self.hsv_apply_failed(self.error.get())
        state=self.state_for(self.document).clut;grid=state.grid
        if not grid.preview_supported:
            return self.hsv_apply_failed('HSV 第三字段非零，语义未确认；已保留原值。可以编辑 H/S 和导出 HSV，不能应用图像。')
        if state.applied_grid!=grid:
            state.applied_grid=grid
            self.request_preview()
        state.applied_hsv_path=state.hsv_path
        self.error.set('');self.update_clut_status()
        if not self.enabled.get():self.clut_status.set('参数已应用 · 调色已旁路')
        return True

    def open_ca_window(self):
        if self.document is None or self.method.get()!='CA 调色':return
        self.ca_window.title(f'CA · Chroma Adjust · {Path(self.document.path).name}')
        self.ca_window.deiconify();self.ca_window.lift()

    def hide_ca_window(self):
        self.ca_editor.release()
        self.ca_window.withdraw()

    def update_ca_status(self):
        if self.document is None:self.ca_status.set('请导入图像');return
        state=self.state_for(self.document).ca
        self.ca_status.set('待应用' if state.curve!=state.applied or state.drafts is not None else '已应用')
        if self.ca_editor.state is state:self.ca_editor.status.set(self.ca_status.get())

    def ca_changed(self,curve):
        if self.document is None:return
        self.state_for(self.document).ca.replace(curve)
        self.update_ca_status()

    def apply_ca_parameters(self):
        if self.document is None or self.method.get()!='CA 调色':return False
        if not self.ca_editor.commit_draft():return False
        state=self.state_for(self.document).ca
        if state.curve!=state.applied:
            state.applied=state.curve
            self.request_preview()
        self.error.set('');self.update_ca_status()
        return True

    def restore_ca_applied(self):
        if self.document is None or self.method.get()!='CA 调色':return
        self.ca_editor._dragging=False;self.ca_editor._preview=None
        state=self.state_for(self.document).ca
        state.drafts=None
        state.replace(state.applied)
        self.ca_editor.show_selection()
        self.error.set('');self.update_ca_status()

    def ca_ready(self):
        if self.document is None or self.method.get()!='CA 调色':
            self.error.set('请先切换到 CA 调色');return False
        if not self.ca_editor.commit_draft():return False
        state=self.state_for(self.document).ca
        if state.curve!=state.applied:
            self.error.set('CA 曲线有未应用修改，请先点击“应用”再导出');return False
        return True

    def load_ca_file(self):
        if self.document is None or self.method.get()!='CA 调色':return
        if self.state_for(self.document).ca.drafts is not None:
            self.error.set('请先提交或恢复当前 CA 数字输入');return
        path=filedialog.askopenfilename(parent=self.ca_window,title='加载 CA 256 点数据',
                                         filetypes=[('CA TXT','*.txt')])
        if not path:return
        try:
            if Path(path).suffix.lower()!='.txt':raise ValueError('请选择 CA .txt 数据文件')
            curve=load_ca_text(path)
            state=self.state_for(self.document).ca
            state.replace(curve)
            state.selected_x=128
            state.drafts=None
            self.ca_editor.set_state(state)
            self.error.set('');self.update_ca_status()
            self.status.set('CA 数据已加载为草稿，请点击“应用”预览')
        except (OSError,UnicodeError,ValueError) as exc:self.error.set(str(exc))

    def export_ca_file(self):
        if not self.ca_ready() or self.io_future is not None:return
        path=filedialog.asksaveasfilename(parent=self.ca_window,title='导出 CA 256 点数据',
             defaultextension='.txt',filetypes=[('CA TXT','*.txt')])
        if not path:return
        if Path(path).suffix.lower()!='.txt':
            self.error.set('CA 数据请保存为 .txt 文件');return
        curve=self.state_for(self.document).ca.applied
        try:
            export_ca_text(path,curve)
            self.error.set('');self.status.set('CA 256 点数据已导出')
        except (OSError,ValueError) as exc:self.error.set(str(exc))

    def sync_method(self):
        selected=self.state_for(self.document).method if self.document is not None else '取色调色'
        clut=selected=='HSV 调色';ca=selected=='CA 调色'
        self.export_menu.entryconfigure(1,label='导出 CA TXT…' if ca else '导出 HSV TXT…' if clut else '导出参数 TXT…',
                                         state='normal' if ca or clut else 'disabled')
        self.method.set(selected)
        self.point_panel.pack_forget();self.clut_panel.pack_forget();self.ca_panel.pack_forget()
        if clut:
            self.clut_editor.set_state(self.state_for(self.document).clut)
            self.clut_panel.pack(fill='x');self.pick.set(False)
            self.clut_window.title(f'HSV 调试 · {Path(self.document.path).name}')
            self.hide_ca_window()
        elif ca:
            self.hide_clut_window()
            self.ca_editor.set_state(self.state_for(self.document).ca)
            self.ca_panel.pack(fill='x');self.pick.set(False)
            self.ca_window.title(f'CA · Chroma Adjust · {Path(self.document.path).name}')
        else:
            self.hide_clut_window();self.hide_ca_window();self.point_panel.pack(fill='x')
        self.update_clut_status();self.update_ca_status()
        self.pick.set(False) if ca else None
        self.pick_button.configure(state='disabled' if ca else 'normal',
             text='定位 HSV（原图 5×5）' if clut else '取色（原图 5×5）')
        self.parameter_canvas.yview_moveto(0)

    def switch_method(self,event=None):
        if self.document is None:self.method.set('取色调色');return
        self.save_draft();self.clut_editor.remember_draft()
        self.clut_editor.wheel_release()
        self.ca_editor.release()
        self.ca_editor.remember_draft()
        state=self.state_for(self.document)
        if state.method==self.method.get():return
        state.method=self.method.get();self.error.set('')
        self.sync_method();self.request_preview()
        if event is not None and self.method.get()=='HSV 调色':self.open_clut_window()
        if event is not None and self.method.get()=='CA 调色':self.open_ca_window()

    def active_key(self):
        if self.document and self.state_for(self.document).method=='CA 调色':
            return ('ca',self.state_for(self.document).ca.applied)
        if self.document and self.state_for(self.document).method=='HSV 调色':
            grid=self.state_for(self.document).clut.applied_grid
            return ('clut',grid)
        return processing_key(self.history.points)

    @staticmethod
    def processor_for_key(key):
        if key and key[0]=='ca':
            return lambda pixels:apply_ca(pixels,key[1])
        if key and key[0]=='clut':
            return lambda pixels:apply_clut(pixels,build_clut(key[1]))
        return lambda pixels:apply_lut(pixels,preview_lut(key))

    def clut_changed(self,grid,final):
        if self.document is None:return
        if final:
            state=self.state_for(self.document).clut
            state.replace(grid)
            if self.clut_editor.state is self.state_for(self.document).clut:
                self.clut_editor.show_node();self.clut_editor.redraw()
            self.update_clut_status()
        else:self.clut_status.set('编辑中 · 待应用')
        # Motion only repaints the local wheel. Image processing is Apply-only.

    def clut_ready(self,require_applied=True):
        if self.document is None or self.state_for(self.document).method!='HSV 调色':
            self.error.set('请先切换到 HSV 调色');return False
        self.clut_editor.remember_draft()
        state=self.state_for(self.document).clut
        if state.drafts or state.strength_draft is not None or state.gain_draft is not None or self.clut_editor._drag_grid is not None:
            self.error.set('存在未提交 HSV 输入，请点击“应用”完成校验');return False
        if require_applied and state.pending():
            self.error.set('HSV 有未应用修改，请先点击“应用”再导出');return False
        return True

    def export_parameter_txt(self):
        if self.method.get()=='CA 调色':self.export_ca_file()
        elif self.method.get()=='HSV 调色':self.save_hsv_file()

    def clut_import_failed(self,exc):
        text=f'导入失败，原数据未替换：{exc}'
        self.error.set(text)
        if self.clut_window.winfo_viewable():messagebox.showerror('HSV 导入失败',text,parent=self.clut_window)

    def load_hsv_file(self):
        if self.document is None or self.method.get()!='HSV 调色':
            self.error.set('请先导入图像并切换到 HSV 调色');return
        editor=self.clut_editor;state=self.state_for(self.document).clut
        editor.remember_draft()
        if state.pending():
            if not messagebox.askyesno('替换 HSV 草稿','导入会替换当前未应用修改，是否继续？',parent=self.clut_window):return
        path=filedialog.askopenfilename(parent=self.clut_window,title='导入三维 HSV TXT · 2700 条记录',filetypes=[('HSV TXT','*.txt')])
        if not path:return
        try:
            if Path(path).suffix.lower()!='.txt':raise ValueError('请选择 HSV .txt 文件')
            grid=load_hsv(path)
            # HSV does not store CLUT Attr: retain the separately entered gains.
            grid=replace(grid,enabled=state.grid.enabled,gains=state.grid.gains)
            editor.close_inline();editor._drag_grid=editor._drag_preview=None;state.drafts.clear();state.strength_draft=None;state.gain_draft=None
            self.clut_changed(grid,True);self.error.set('')
            state.hsv_path=str(path)
            state.import_note=f'已导入 {Path(path).name} · 2700 个节点'
            if not grid.preview_supported:
                state.import_note+=' · 第三字段未确认'
            # Editing is fixed to the center layer; imports never auto-expand.
            planes=[grid.plane(i) for i in range(9)]
            active=[np.flatnonzero((abs(np.asarray(p.dh))>1e-10)|(abs(np.asarray(p.ds))>1e-10)) for p in planes]
            index=4
            row,column=divmod(int(active[index][0]),12) if len(active[index]) else (0,4)
            state.slice_index=index;editor.show_node();editor.locate_sample(row,column)
            self.update_clut_status();self.status.set(state.import_note)
        except (OSError,UnicodeError,ValueError) as exc:self.clut_import_failed(exc)

    def save_hsv_file(self):
        if self.document is None or self.method.get()!='HSV 调色':return
        if not isinstance(self.state_for(self.document).clut.grid,HSVGrid):
            self.error.set('当前参数不是 HSV 格式');return
        if not self.clut_editor.commit_all():return
        path=filedialog.asksaveasfilename(parent=self.clut_window,title='导出 HSV TXT · 当前编辑参数',
                                         defaultextension='.txt',filetypes=[('HSV TXT','*.txt')])
        if not path:return
        try:
            if Path(path).suffix.lower()!='.txt':raise ValueError('HSV 参数请保存为 .txt')
            export_hsv(path,self.state_for(self.document).clut.grid)
            gains=self.state_for(self.document).clut.grid.gains
            self.error.set('');self.status.set(f'HSV TXT 已导出；CLUT Attr 需在设备另填 gain_r/g/b={gains}，图像应用状态不变')
        except (OSError,ValueError) as exc:self.error.set(str(exc))

    def scroll_parameters(self,event):
        bounds=self.parameter_canvas.bbox('all')
        if bounds and bounds[3]>self.parameter_canvas.winfo_height():
            self.parameter_canvas.yview_scroll(-3 if event.delta>0 else 3,'units')
        return 'break'

    @property
    def document(self):
        return self._active_document

    def state_for(self,document):
        # A 2700-node HSV default is sizeable; do not build it on every lookup.
        if document.document_id not in self.states:
            self.states[document.document_id]=GradingState()
        return self.states[document.document_id]

    @property
    def history(self):
        return self.state_for(self.document).history if self.document else self._empty_history

    def selected_point(self):
        return self.history.points[self.selected] if 0<=self.selected<len(self.history.points) else None

    def toggle_enabled(self):
        if self.document:self.state_for(self.document).enabled=self.enabled.get()
        self.schedule_draw()

    def save_draft(self):
        point=self.selected_point()
        if self.document and point:
            state=self.state_for(self.document)
            state.selected_id=point.point_id
            state.drafts[point.point_id]=dict(values={g:[v.get() for v in vs] for g,vs in self.values.items()},
                rendered=copy.deepcopy(self._rendered),radius=self.radius.get(),strength=self.strength.get(),error=self.error.get())

    def defer_commit(self,callback):
        token=self._editor_epoch
        def commit():
            if token!=self._editor_epoch or not self.winfo_ismapped():return
            focus=self.focus_get()
            # Navigation must retain a draft, never implicitly apply it. Only
            # ordinary moves within numeric entries commit on focus loss.
            if isinstance(focus,ttk.Entry) and not isinstance(focus,ttk.Combobox):callback()
        self.later(0,commit)

    def later(self,ms,callback):
        def run():
            self._timers.discard(identifier)
            if not self.closed:
                callback()
        identifier=self.after(ms,run)
        self._timers.add(identifier)
        return identifier

    def open_images(self):
        if self.io_future is not None:
            self.status.set('正在读写图像，请稍候')
            return
        paths=filedialog.askopenfilenames(parent=self,title='导入彩色图像',filetypes=[('Colour images','*.png *.jpg *.jpeg *.tif *.tiff')])
        if not paths:
            return
        def load():
            documents,errors=[],[]
            for path in paths:
                try: documents.append(read_color_image(path))
                except Exception as exc: errors.append(f'{Path(path).name}: {exc}')
            return documents,errors
        self.status.set('正在导入…')
        self.io_future=self.executor.submit(load)
        self.later(40,self.poll_import)

    def poll_import(self):
        if not self.io_future.done():
            self.later(40,self.poll_import)
            return
        documents,errors=self.io_future.result()
        self.io_future=None
        first=len(self.documents)
        self.documents.extend(documents)
        self.refresh_files()
        if documents: self.select_document(first)
        if errors: self.error.set('\n'.join(errors))

    def refresh_files(self):
        self.file_combo['values']=[f'{i+1} · {Path(d.path).name}' for i,d in enumerate(self.documents)]

    def select_document(self,index):
        if not 0 <= index < len(self.documents): return
        if self.document is self.documents[index]:
            self.index=index
            return
        self.save_draft()
        self.clut_editor.remember_draft()
        if self.document:self.clut_editor.wheel_release()
        if self.document:self.ca_editor.release()
        if self.document:self.ca_editor.remember_draft()
        self._influence_cache=None
        self.store_view()
        self.index=index
        self._active_document=self.documents[index]
        self._editor_epoch+=1
        grading=self.state_for(self.document)
        self.enabled.set(grading.enabled)
        self.selected=next((i for i,p in enumerate(grading.history.points) if p.point_id==grading.selected_id),-1)
        self.refresh_files()
        self.file_combo.current(index)
        rgb=self.document.rgb
        h,w=rgb.shape[:2]
        scale=min(1,1000/max(h,w))
        self.source=cv2.resize(rgb,(max(1,round(w*scale)),max(1,round(h*scale))),interpolation=cv2.INTER_AREA)
        self.output=self.source.copy()
        self.source_pil=self.make_display(self.source)
        self.output_pil=self.source_pil
        state=self.document.view_state
        self.fit=state.get('fit',True)
        self.zoom=state.get('zoom',1.0)
        self.offset=list(state.get('offset',(0.,0.)))
        self.divider=state.get('divider',.5)
        self.drag=None
        self.hold_original=False
        self.refresh_points()
        self.sync_method()
        self.schedule_draw()
        self.request_preview()

    def store_view(self):
        if self.document is not None:
            self.state_for(self.document).enabled=self.enabled.get()
            self.document.view_state=dict(fit=self.fit,zoom=self.zoom,offset=list(self.offset),
                                          divider=self.divider)

    def make_display(self,rgb):
        if self.document.alpha is not None:
            alpha=cv2.resize(self.document.alpha,(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_AREA)[...,None]
            rgb=rgb*alpha+(1-alpha)*.44
        return Image.fromarray(raster8(rgb))

    def remove_document(self):
        if self.document is None: return
        self.clut_editor.wheel_release()
        self.ca_editor.release()
        self._influence_cache=None
        index=next(i for i,d in enumerate(self.documents) if d is self.document)
        self.states.pop(self.document.document_id,None)
        self.documents.pop(index)
        self._active_document=None
        self.selected=-1
        self._editor_epoch+=1
        self.index=-1
        self.refresh_files()
        self.revision+=1
        if self.documents: self.select_document(min(index,len(self.documents)-1))
        else:
            self.index=-1
            self.source=self.output=self.source_pil=self.output_pil=None
            self.file_combo.set('')
            self.refresh_points()
            self.sync_method()
            self.schedule_draw()

    def refresh_points(self):
        self.point_list.delete(*self.point_list.get_children())
        self._point_rows={}
        points=self.history.points
        for image_index,document in enumerate(self.documents):
            for p in self.state_for(document).history.points:
                self.point_list.insert('', 'end', iid=p.point_id,text=p.name or '未命名',
                    values=(f'{image_index+1} · {Path(document.path).name}',))
                self._point_rows[p.point_id]=(document.document_id,p.point_id)
        self.selected=min(self.selected,len(points)-1)
        if self.selected>=0:
            self.point_list.selection_set(points[self.selected].point_id)
            self.show_point()
        else:
            self._editor_epoch+=1
            self.error.set('')
            self.original_label.configure(text='Original · 在图像上取色')
            self.swatches.delete('all')
            for variables in self.values.values():
                for var in variables:var.set('0')
            self._rendered={g:['0']*3 for g in self.values}
            self.radius.set('25');self.strength.set('100')
        self.undo_button.configure(state='normal' if self.history.undo_stack else 'disabled')
        self.redo_button.configure(state='normal' if self.history.redo_stack else 'disabled')
        self.update_draft_status()

    def select_point(self,event=None):
        selected=self.point_list.selection()
        if not selected or selected[0] not in self._point_rows:return
        owner,point_id=self._point_rows[selected[0]]
        current=self.selected_point()
        if self.document and self.document.document_id==owner and current and current.point_id==point_id:return
        self.save_draft()
        index=next((i for i,d in enumerate(self.documents) if d.document_id==owner),None)
        if index is None:return
        self.select_document(index)
        self.selected=next(i for i,p in enumerate(self.history.points) if p.point_id==point_id)
        self.point_list.selection_set(point_id)
        self.point_list.see(point_id)
        self.show_point()

    def point_details(self):
        selected=self.point_list.selection()
        hovered=self.point_list.identify_row(self.point_list.winfo_pointery()-self.point_list.winfo_rooty())
        if hovered:selected=(hovered,)
        if not selected or selected[0] not in self._point_rows:return '色块仅作用于所属图像；双击名称重命名'
        owner,point_id=self._point_rows[selected[0]]
        document=next((d for d in self.documents if d.document_id==owner),None)
        if document is None:return ''
        point=next(p for p in self.state_for(document).history.points if p.point_id==point_id)
        return f'{point.name}\n所属：{document.path}\n取样：{point.origin}\nOriginal RGB {tuple(round(v*255) for v in point.source)}\nTarget RGB {tuple(round(v*255) for v in point.target)}'

    def rename_point(self,event=None,name=None):
        if event is not None:
            row=self.point_list.identify_row(event.y)
            if not row:return 'break'
            self.point_list.selection_set(row);self.select_point()
        point=self.selected_point()
        if point is None:return 'break'
        self.save_draft()
        if name is None:name=simpledialog.askstring('重命名色块','名称',initialvalue=point.name,parent=self)
        if name is None:return 'break'
        if not name.strip():self.error.set('色块名称不能为空');return 'break'
        points=copy.deepcopy(self.history.points);points[self.selected].name=name.strip()
        self.edit(points,keep_draft=True)
        return 'break'

    def point_menu(self,event):
        row=self.point_list.identify_row(event.y)
        if row:self.point_list.selection_set(row);self.select_point()
        self.show_point_menu(event)
        return 'break'

    def show_point_menu(self,event=None):
        if self.selected_point() is None:return
        menu=self.point_context;menu.delete(0,'end')
        menu.add_command(label='重命名',command=self.rename_point)
        menu.add_command(label='删除',command=self.delete_point)
        copy_menu=tk.Menu(menu,tearoff=False)
        # Destroy old submenus as well as their menu entries.
        for child in menu.winfo_children():
            if child is not copy_menu:child.destroy()
        for i,d in enumerate(self.documents):
            if d is not self.document:
                copy_menu.add_command(label=f'{i+1} · {Path(d.path).name}',command=lambda target=d.document_id:self.copy_point_to(target))
        menu.add_cascade(label='复制调整到图像',menu=copy_menu,state='normal' if len(self.documents)>1 else 'disabled')
        try:menu.tk_popup(event.x_root if event else self.winfo_pointerx(),event.y_root if event else self.winfo_pointery())
        finally:menu.grab_release()

    def copy_point_to(self,document_id):
        point=self.selected_point()
        target=next((d for d in self.documents if d.document_id==document_id),None)
        if point is None or target is None or target is self.document:return
        if self.has_draft():self.error.set('请先提交或重置当前色块的输入，再复制调整');return
        clone=copy.deepcopy(point);clone.point_id=uuid4().hex;clone.owner_id=target.document_id
        state=self.state_for(target)
        state.history.replace(state.history.points+[clone]);state.cache_key=None;state.output=None
        self.refresh_points()

    def show_point(self):
        self._editor_epoch+=1
        p=self.history.points[self.selected]
        state=self.state_for(self.document);state.selected_id=p.point_id
        hsv=colorsys.rgb_to_hsv(*p.source)
        self.original_label.configure(text=f'Original RGB  {tuple(round(v*255) for v in p.source)}\nHSV  {hsv[0]*360:.1f}° / {hsv[1]:.3f} / {hsv[2]:.3f}')
        target_hsv=colorsys.rgb_to_hsv(*p.target)
        for group,values in (('RGB',[v*255 for v in p.target]),('HSV',[target_hsv[0]*360,target_hsv[1],target_hsv[2]])):
            precision=(1,1,1) if group=='RGB' else (1,3,3)
            texts=[format_number(v,d) for v,d in zip(values,precision)]
            for var,text in zip(self.values[group],texts): var.set(text)
            self._rendered[group]=texts
        self.radius.set(format_number(p.radius,1))
        self.strength.set(format_number(p.strength*100,1))
        self.error.set('')
        draft=state.drafts.get(p.point_id)
        if draft:
            for group,texts in draft['values'].items():
                for var,text in zip(self.values[group],texts):var.set(text)
            self._rendered=copy.deepcopy(draft['rendered'])
            self.radius.set(draft['radius']);self.strength.set(draft['strength']);self.error.set(draft['error'])
        self.swatches.delete('all')
        for x,color in ((0,p.source),(122,p.target)):
            fill='#%02x%02x%02x'%tuple(round(v*255) for v in color)
            self.swatches.create_rectangle(x,0,x+110,24,fill=fill,outline=COLORS['border'])
        self.update_draft_status()

    def has_draft(self):
        point=self.selected_point()
        if point is None:return False
        return (any([v.get().strip() for v in vs]!=self._rendered.get(g) for g,vs in self.values.items())
                or self.radius.get()!=format_number(point.radius,1) or self.strength.get()!=format_number(point.strength*100,1))

    def update_draft_status(self,*_):
        self.draft_status.set('未提交输入 · Enter 确认' if self.has_draft() else '')

    def commit_target(self,group):
        if self.selected<0: return 'break'
        texts=[v.get().strip() for v in self.values[group]]
        if texts==self._rendered.get(group): return 'break'
        try:
            point=self.selected_point()
            hsv=colorsys.rgb_to_hsv(*point.target)
            precise=[v*255 for v in point.target] if group=='RGB' else [hsv[0]*360,hsv[1],hsv[2]]
            values=[old if text==shown else float(text)
                    for text,shown,old in zip(texts,self._rendered[group],precise)]
            maximum=(255,255,255) if group=='RGB' else (360,1,1)
            if any(not math.isfinite(v) or not 0<=v<=m for v,m in zip(values,maximum)):
                raise ValueError(f'{group} 范围：{maximum}')
            target=tuple(v/255 for v in values) if group=='RGB' else colorsys.hsv_to_rgb(values[0]/360,values[1],values[2])
            points=copy.deepcopy(self.history.points)
            points[self.selected].target=target
            self.edit(points)
        except ValueError as exc: self.error.set(f'请输入合法数字：{exc}')
        return 'break'

    def commit_influence(self,event=None):
        if self.selected<0: return 'break'
        try:
            point=self.selected_point()
            radius=point.radius if self.radius.get()==format_number(point.radius,1) else float(self.radius.get())
            strength=point.strength*100 if self.strength.get()==format_number(point.strength*100,1) else float(self.strength.get())
            if not 5<=radius<=100 or not 0<=strength<=100: raise ValueError('范围 5…100，强度 0…100')
            points=copy.deepcopy(self.history.points)
            points[self.selected].radius=radius
            points[self.selected].strength=strength/100
            self.edit(points)
        except ValueError as exc: self.error.set(str(exc))
        return 'break'

    def edit(self,points,keep_draft=False):
        if self.document is None:return
        points=copy.deepcopy(points)
        for i,p in enumerate(points):
            if p.owner_id and p.owner_id!=self.document.document_id:
                raise ValueError('不能直接使用其他图像的色块，请显式复制调整')
            p.owner_id=self.document.document_id
            if not p.name:p.name=f'颜色 {i+1}'
            if not p.origin:p.origin=self.document.path
        before=processing_key(self.history.points)
        previous=self.selected_point()
        if self.history.replace(points):
            state=self.state_for(self.document)
            if not keep_draft:
                if previous:state.drafts.pop(previous.point_id,None)
            valid={p.point_id for p in points}
            state.drafts={k:v for k,v in state.drafts.items() if k in valid}
            self.refresh_points()
            if before!=processing_key(points):self.request_preview()
        self.update_draft_status()

    def delete_point(self):
        if self.selected>=0:
            points=copy.deepcopy(self.history.points)
            points.pop(self.selected)
            self.edit(points)

    def reset_point(self):
        if self.selected>=0:
            points=copy.deepcopy(self.history.points)
            point=points[self.selected];point.target=point.source;point.radius=25.;point.strength=1.;point.enabled=True
            self.edit(points)
            self.state_for(self.document).drafts.pop(point.point_id,None)
            self.show_point()

    def reset_all(self):
        if self.history.points and messagebox.askyesno('重置本图调色', '只清空当前图像的颜色控制点，可通过撤销恢复。是否继续？',parent=self):
            self.edit([])

    def travel(self,redo):
        before=processing_key(self.history.points)
        if (self.history.redo() if redo else self.history.undo()):
            self.state_for(self.document).drafts.clear()
            self.selected=0 if self.history.points else -1
            self.refresh_points()
            if before!=processing_key(self.history.points):self.request_preview()

    def request_preview(self):
        self.revision+=1
        self.status.set('正在更新当前图像…' if self.document else '请导入图像')
        self.schedule_draw()
        if self.future is None: self.start_preview()

    def preview_processor(self):
        if not self.enabled.get():
            return lambda pixels: pixels
        return self.processor_for_key(self.active_key())

    def start_preview(self):
        if self.document is None: return
        revision=self.revision
        document_id=self.document.document_id
        points=copy.deepcopy(self.history.points)
        key=self.active_key()
        state=self.state_for(self.document)
        if state.cache_key==key and state.output is not None:
            self.output=state.output;self.output_pil=self.make_display(self.output)
            self._shown_revision=revision
            self.status.set(f'{Path(self.document.path).name} · {len(points)} 个控制点')
            self.schedule_draw();return
        source=self.source
        self._running_revision=revision
        def process():
            return revision,document_id,key,GradingWorkspace.processor_for_key(key)(source)
        self.future=self.executor.submit(process)
        self.later(30,self.poll_preview)

    def poll_preview(self):
        if not self.future.done():
            self.later(30,self.poll_preview)
            return
        future,self.future=self.future,None
        try:
            revision,document_id,key,result=future.result()
            if revision==self.revision and self.document and document_id==self.document.document_id and key==self.active_key():
                state=self.state_for(self.document);state.cache_key=key;state.output=result
                self.output=result
                self.output_pil=self.make_display(result)
                self._shown_revision=revision
                self.status.set(f'{self.document.note} · {self.document.rgb.shape[1]}×{self.document.rgb.shape[0]} · RGB /255 · {len(self.history.points)} 个控制点')
                self.schedule_draw()
            elif self.document:
                self.start_preview()
        except Exception as exc:
            if self.document and getattr(self,'_running_revision',None)!=self.revision:self.start_preview()
            else:self.error.set(str(exc))

    def press(self,event):
        if self.document is None: return 'break'
        if self.mode.get()=='滑动对比' and abs(event.x-self.canvas.winfo_width()*self.divider)<9:
            self.drag=('split',)
        elif self.pick.get():
            x,y,_=self.coordinates(event)
            if 0<=x<self.source.shape[1] and 0<=y<self.source.shape[0]:
                fx=int(x*self.document.rgb.shape[1]/self.source.shape[1]);fy=int(y*self.document.rgb.shape[0]/self.source.shape[0])
                if self.method.get()=='HSV 调色':
                    self.pick_clut_at(fx,fy);return 'break'
                if self.document.alpha is not None and self.document.alpha[fy,fx]<.1:
                    self.error.set('请在非透明区域取色')
                    return 'break'
                color=sample_original(self.document.rgb,fx,fy)
                self.save_draft()
                self.selected=len(self.history.points)
                self.edit(self.history.points+[ColorPoint(color,color,origin=self.document.path)])
                self.pick.set(False)
        else:
            self.drag=None
        return 'break'

    def export(self):
        if self.document is None or self.io_future is not None: return
        # Clicking a ttk button does not always move keyboard focus. Validate
        # the visible draft before taking the export snapshot as well.
        is_clut=self.method.get()=='HSV 调色'
        is_ca=self.method.get()=='CA 调色'
        if is_clut and not self.clut_ready():return
        if is_ca and not self.ca_ready():return
        if self.selected>=0 and not is_clut and not is_ca:
            for group in ('RGB','HSV'):
                self.commit_target(group)
                if self.error.get():return
            self.commit_influence()
            if self.error.get():return
        path=filedialog.asksaveasfilename(parent=self,title='导出最终调色结果 · sRGB · 不含对比线',defaultextension='.png',filetypes=[('PNG 8-bit','*.png'),('TIFF 16-bit','*.tif *.tiff')])
        if not path: return
        document=self.document
        points=copy.deepcopy(self.history.points) if self.enabled.get() else []
        processor=self.preview_processor()
        def save():
            if is_clut or is_ca:export_processed_image(path,document,processor)
            else:export_color_image(path,document,build_lut(points))
        self.io_future=self.executor.submit(save)
        self.status.set('正在导出完整图像…')
        self.later(40,self.poll_export)

    def poll_export(self):
        if not self.io_future.done():
            self.later(40,self.poll_export)
            return
        future,self.io_future=self.io_future,None
        try:
            report=future.result()
            self.status.set('导出完成')
        except Exception as exc: self.error.set(str(exc))

    def destroy(self):
        self.closed=True
        self.cancel_detail()
        for var,trace in self._draft_traces:var.trace_remove('write',trace)
        for identifier in list(self._timers): self.after_cancel(identifier)
        self._timers.clear()
        self.executor.shutdown(wait=False,cancel_futures=True)
        super().destroy()
