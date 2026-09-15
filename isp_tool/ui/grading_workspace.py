"""Embedded manual grading workspace: source picking and final comparison."""
import colorsys
import copy
import math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk
from ..grading.model import GradeHistory, ColorPoint, build_lut, apply_lut, raster8, sample_original
from ..grading.image_io import read_color_image, export_color_image
from .theme import COLORS
from .widgets.tooltip import Tooltip
from .widgets.tool_selector import ToolSelector


class GradingWorkspace(ttk.Frame):
    def __init__(self,parent,on_back,tool_variable=None,on_tool=None):
        super().__init__(parent)
        self.on_back=on_back
        self.history=GradeHistory()
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
        self.export_button=ttk.Button(bar,text='导出结果',command=self.export)
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
        def size_parameters(event):
            # Use the actual font/control request, not hard-coded physical
            # pixels; Windows 150/200% DPI otherwise clips the third column.
            self.parameter_canvas.configure(width=max(315,right.winfo_reqwidth()),
                                            scrollregion=self.parameter_canvas.bbox('all'))
        right.bind('<Configure>',size_parameters)
        self.parameter_canvas.bind('<Configure>',lambda e:self.parameter_canvas.itemconfigure(parameter_window,width=e.width))
        left=ttk.Frame(body)
        left.pack(side='left',fill='both',expand=True)
        tools=ttk.Frame(left)
        tools.pack(fill='x',pady=(0,6))
        self.pick=tk.BooleanVar(self,value=False)
        ttk.Checkbutton(tools,text='取色（原图 5×5）',variable=self.pick).pack(side='left')
        self.mode=tk.StringVar(self,value='左右并排')
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
        ttk.Checkbutton(view_tools,text='启用调色',variable=self.enabled,command=self.schedule_draw).pack(side='left')
        self.canvas=tk.Canvas(left,bg='#707070',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.schedule_draw())
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',lambda e:setattr(self,'drag',None))
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Motion>',self.hover)
        ttk.Label(right,text='共用颜色控制点',style='Title.TLabel').pack(anchor='w')
        self.point_list=tk.Listbox(right,height=7,width=29,exportselection=False,
                                   bg=COLORS['panel_alt'],fg=COLORS['foreground'],
                                   selectbackground=COLORS['accent'],selectforeground='white')
        self.point_list.pack(fill='x',pady=6)
        self.point_list.bind('<<ListboxSelect>>',self.select_point)
        Tooltip(self.point_list,lambda: ('取色来源：'+self.history.points[self.selected].origin) if 0<=self.selected<len(self.history.points) else '所有图像共用；始终从原图取色')
        action=ttk.Frame(right)
        action.pack(fill='x')
        ttk.Button(action,text='删除',command=self.delete_point,width=6).pack(side='left')
        ttk.Button(action,text='重置当前',command=self.reset_point).pack(side='left',padx=5)
        ttk.Button(action,text='重置全部',command=self.reset_all).pack(side='left')
        self.original_label=ttk.Label(right,text='Original · 未取色',justify='left')
        self.original_label.pack(anchor='w',pady=(12,3))
        self.swatches=tk.Canvas(right,width=235,height=25,highlightthickness=0)
        self.swatches.pack(anchor='w',pady=3)
        self.values={}
        for group,names in (('RGB',('R','G','B')),('HSV',('H°','S%','V%'))):
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
                entry.bind('<FocusOut>',lambda e,g=group:self.commit_target(g))
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
            entry.bind('<FocusOut>',self.commit_influence)
        self.error=tk.StringVar(self)
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

    def scroll_parameters(self,event):
        bounds=self.parameter_canvas.bbox('all')
        if bounds and bounds[3]>self.parameter_canvas.winfo_height():
            self.parameter_canvas.yview_scroll(-3 if event.delta>0 else 3,'units')
        return 'break'

    @property
    def document(self):
        return self.documents[self.index] if 0 <= self.index < len(self.documents) else None

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
            return
        self.store_view()
        self.index=index
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
        self.mode.set(state.get('mode','左右并排'))
        self.drag=None
        self.hold_original=False
        self.schedule_draw()
        self.request_preview()

    def store_view(self):
        if self.document is not None:
            self.document.view_state=dict(fit=self.fit,zoom=self.zoom,offset=list(self.offset),
                                          divider=self.divider,mode=self.mode.get())

    def make_display(self,rgb):
        if self.document.alpha is not None:
            alpha=cv2.resize(self.document.alpha,(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_AREA)[...,None]
            rgb=rgb*alpha+(1-alpha)*.44
        return Image.fromarray(raster8(rgb))

    def remove_document(self):
        if self.document is None: return
        index=self.index
        self.documents.pop(index)
        self.index=-1
        self.refresh_files()
        self.revision+=1
        if self.documents: self.select_document(min(index,len(self.documents)-1))
        else:
            self.index=-1
            self.source=self.output=self.source_pil=self.output_pil=None
            self.file_combo.set('')
            self.schedule_draw()

    def refresh_points(self):
        self.point_list.delete(0,'end')
        points=self.history.points
        for i,p in enumerate(points):
            rgb=tuple(round(c*255) for c in p.source)
            self.point_list.insert('end',f'{i+1:02}  RGB {rgb}')
        self.selected=min(self.selected,len(points)-1)
        if self.selected>=0:
            self.point_list.selection_set(self.selected)
            self.show_point()
        else:
            self.original_label.configure(text='Original · 在图像上取色')
            self.swatches.delete('all')
        self.undo_button.configure(state='normal' if self.history.undo_stack else 'disabled')
        self.redo_button.configure(state='normal' if self.history.redo_stack else 'disabled')

    def select_point(self,event=None):
        selected=self.point_list.curselection()
        if selected:
            self.selected=selected[0]
            self.show_point()

    def show_point(self):
        p=self.history.points[self.selected]
        hsv=colorsys.rgb_to_hsv(*p.source)
        self.original_label.configure(text=f'Original RGB  {tuple(round(v*255) for v in p.source)}\nHSV  {hsv[0]*360:.1f}° / {hsv[1]*100:.1f}% / {hsv[2]*100:.1f}%')
        target_hsv=colorsys.rgb_to_hsv(*p.target)
        for group,values in (('RGB',[v*255 for v in p.target]),('HSV',[target_hsv[0]*360,target_hsv[1]*100,target_hsv[2]*100])):
            texts=[f'{v:.4f}'.rstrip('0').rstrip('.') or '0' for v in values]
            for var,text in zip(self.values[group],texts): var.set(text)
            self._rendered[group]=texts
        self.radius.set(f'{p.radius:g}')
        self.strength.set(f'{p.strength*100:g}')
        self.error.set('')
        self.swatches.delete('all')
        for x,color in ((0,p.source),(122,p.target)):
            fill='#%02x%02x%02x'%tuple(round(v*255) for v in color)
            self.swatches.create_rectangle(x,0,x+110,24,fill=fill,outline=COLORS['border'])

    def commit_target(self,group):
        if self.selected<0: return 'break'
        texts=[v.get().strip() for v in self.values[group]]
        if texts==self._rendered.get(group): return 'break'
        try:
            values=[float(v) for v in texts]
            maximum=(255,255,255) if group=='RGB' else (360,100,100)
            if any(not math.isfinite(v) or not 0<=v<=m for v,m in zip(values,maximum)):
                raise ValueError(f'{group} 范围：{maximum}')
            target=tuple(v/255 for v in values) if group=='RGB' else colorsys.hsv_to_rgb(values[0]/360,values[1]/100,values[2]/100)
            points=copy.deepcopy(self.history.points)
            points[self.selected].target=target
            self.edit(points)
        except ValueError as exc: self.error.set(f'请输入合法数字：{exc}')
        return 'break'

    def commit_influence(self,event=None):
        if self.selected<0: return 'break'
        try:
            radius,strength=float(self.radius.get()),float(self.strength.get())
            if not 5<=radius<=100 or not 0<=strength<=100: raise ValueError('范围 5…100，强度 0…100')
            points=copy.deepcopy(self.history.points)
            points[self.selected].radius=radius
            points[self.selected].strength=strength/100
            self.edit(points)
        except ValueError as exc: self.error.set(str(exc))
        return 'break'

    def edit(self,points):
        if self.history.replace(points):
            self.refresh_points()
            self.request_preview()

    def delete_point(self):
        if self.selected>=0:
            points=copy.deepcopy(self.history.points)
            points.pop(self.selected)
            self.edit(points)

    def reset_point(self):
        if self.selected>=0:
            points=copy.deepcopy(self.history.points)
            points[self.selected]=ColorPoint(points[self.selected].source,points[self.selected].source,origin=points[self.selected].origin)
            self.edit(points)

    def reset_all(self):
        if self.history.points and messagebox.askyesno('重置共用调色', '将清空所有图像共用的颜色控制点，可通过撤销恢复。是否继续？',parent=self):
            self.edit([])

    def travel(self,redo):
        if (self.history.redo() if redo else self.history.undo()):
            self.selected=0 if self.history.points else -1
            self.refresh_points()
            self.request_preview()

    def request_preview(self):
        self.revision+=1
        self.status.set('正在更新当前图像 · 所有图像共用调色…' if self.document else '导入图像即可应用当前共用调色')
        if self.future is None: self.start_preview()

    def start_preview(self):
        if self.document is None: return
        revision=self.revision
        points=copy.deepcopy(self.history.points)
        source=self.source
        def process():
            lut=build_lut(points)
            return revision,lut,apply_lut(source,lut)
        self.future=self.executor.submit(process)
        self.later(30,self.poll_preview)

    def poll_preview(self):
        if not self.future.done():
            self.later(30,self.poll_preview)
            return
        future,self.future=self.future,None
        try:
            revision,lut,result=future.result()
            if revision==self.revision and self.document:
                self.output=result
                self.output_pil=self.make_display(result)
                self._shown_revision=revision
                self.status.set(f'{self.document.note} · {self.document.rgb.shape[1]}×{self.document.rgb.shape[0]} · RGB /255 · {len(self.history.points)} 个控制点')
                self.schedule_draw()
            elif self.document:
                self.start_preview()
        except Exception as exc: self.error.set(str(exc))

    def fit_image(self):
        self.fit=True
        self.schedule_draw()

    def show_original(self,value):
        self.hold_original=value
        self.schedule_draw()

    def schedule_draw(self):
        if self._render_timer is None: self._render_timer=self.later(16,self.draw)

    def draw(self):
        self._render_timer=None
        self.canvas.delete('all')
        self._photos=[]
        if self.source_pil is None:
            self.canvas.create_text(30,30,anchor='nw',text='导入彩色图像，然后启用“取色”添加控制点',fill='white')
            return
        w,h=max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
        side=self.mode.get()=='左右并排'
        pw=max(1,w//2) if side else w
        iw,ih=self.source_pil.size
        if self.fit:
            self.zoom=min(pw/iw,h/ih)
            self.offset=[(pw-iw*self.zoom)/2,(h-ih*self.zoom)/2]
        ready=self._shown_revision==self.revision
        corrected=self.source_pil if self.hold_original or not self.enabled.get() or not ready else self.output_pil
        def viewport(image):
            ox,oy=self.offset
            x0=max(0,math.floor(-ox/self.zoom));y0=max(0,math.floor(-oy/self.zoom))
            x1=min(iw,math.ceil((pw-ox)/self.zoom));y1=min(ih,math.ceil((h-oy)/self.zoom))
            view=Image.new('RGB',(pw,h),(112,112,112))
            if x1>x0 and y1>y0:
                crop=image.crop((x0,y0,x1,y1))
                crop=crop.resize((max(1,round((x1-x0)*self.zoom)),max(1,round((y1-y0)*self.zoom))),Image.Resampling.NEAREST if self.zoom>=2 else Image.Resampling.BILINEAR)
                view.paste(crop,(round(ox+x0*self.zoom),round(oy+y0*self.zoom)))
            return view
        before,after=viewport(self.source_pil),viewport(corrected)
        if side:
            views=[(0,before),(pw,after)]
        else:
            split=round(pw*self.divider)
            before.paste(after.crop((split,0,pw,h)),(split,0))
            views=[(0,before)]
        for x,view in views:
            photo=ImageTk.PhotoImage(view,master=self)
            self._photos.append(photo)
            self.canvas.create_image(x,0,image=photo,anchor='nw')
        self.canvas.create_text(10,10,anchor='nw',text='原图 / Before',fill='white')
        self.canvas.create_text(w-10,10,anchor='ne',text='最终效果 / After' if ready or not self.enabled.get() else '正在更新…',fill='white')
        self.canvas.create_line(pw if side else w*self.divider,0,pw if side else w*self.divider,h,fill='#ffffff',width=2)

    def coordinates(self,event):
        w=max(1,self.canvas.winfo_width())
        pw=w//2 if self.mode.get()=='左右并排' else w
        local=event.x%max(1,pw) if self.mode.get()=='左右并排' else event.x
        return (local-self.offset[0])/self.zoom,(event.y-self.offset[1])/self.zoom,local

    def press(self,event):
        if self.document is None: return 'break'
        if self.mode.get()=='滑动对比' and abs(event.x-self.canvas.winfo_width()*self.divider)<9:
            self.drag=('split',)
        elif self.pick.get():
            x,y,_=self.coordinates(event)
            if 0<=x<self.source.shape[1] and 0<=y<self.source.shape[0]:
                fx=int(x*self.document.rgb.shape[1]/self.source.shape[1]);fy=int(y*self.document.rgb.shape[0]/self.source.shape[0])
                if self.document.alpha is not None and self.document.alpha[fy,fx]<.1:
                    self.error.set('请在非透明区域取色')
                    return 'break'
                color=sample_original(self.document.rgb,fx,fy)
                self.selected=len(self.history.points)
                self.edit(self.history.points+[ColorPoint(color,color,origin=self.document.path)])
                self.pick.set(False)
        else:
            self.fit=False
            self.drag=('pan',event.x,event.y,*self.offset)
        return 'break'

    def motion(self,event):
        if self.drag:
            if self.drag[0]=='split': self.divider=max(.02,min(.98,event.x/max(1,self.canvas.winfo_width())))
            else: self.offset=[self.drag[3]+event.x-self.drag[1],self.drag[4]+event.y-self.drag[2]]
            self.schedule_draw()
        return 'break'

    def wheel(self,event):
        if self.document is not None:
            x,y,local=self.coordinates(event)
            self.fit=False
            self.zoom=max(.02,min(32,self.zoom*(1.15 if event.delta>0 else 1/1.15)))
            self.offset=[local-x*self.zoom,event.y-y*self.zoom]
            self.schedule_draw()
        return 'break'

    def hover(self,event):
        if self.source is None: return
        x,y,_=self.coordinates(event)
        x,y=int(x),int(y)
        if 0<=x<self.source.shape[1] and 0<=y<self.source.shape[0]:
            before=tuple(raster8(self.source[y,x]).tolist())
            after=tuple(raster8((self.output if self.enabled.get() and self._shown_revision==self.revision else self.source)[y,x]).tolist())
            self.status.set(f'Preview ({x},{y}) · Before RGB {before} · After RGB {after} /255')

    def export(self):
        if self.document is None or self.io_future is not None: return
        # Clicking a ttk button does not always move keyboard focus. Validate
        # the visible draft before taking the export snapshot as well.
        if self.selected>=0:
            for group in ('RGB','HSV'):
                self.commit_target(group)
                if self.error.get():return
            self.commit_influence()
            if self.error.get():return
        path=filedialog.asksaveasfilename(parent=self,title='导出最终调色结果 · sRGB · 不含对比线',defaultextension='.png',filetypes=[('PNG 8-bit','*.png'),('TIFF 16-bit','*.tif *.tiff')])
        if not path: return
        document=self.document
        points=copy.deepcopy(self.history.points) if self.enabled.get() else []
        def save(): export_color_image(path,document,build_lut(points))
        self.io_future=self.executor.submit(save)
        self.status.set('正在导出完整图像…')
        self.later(40,self.poll_export)

    def poll_export(self):
        if not self.io_future.done():
            self.later(40,self.poll_export)
            return
        future,self.io_future=self.io_future,None
        try:
            future.result()
            self.status.set('导出完成 · sRGB')
        except Exception as exc: self.error.set(str(exc))

    def destroy(self):
        self.closed=True
        for identifier in list(self._timers): self.after_cancel(identifier)
        self._timers.clear()
        self.executor.shutdown(wait=False,cancel_futures=True)
        super().destroy()
