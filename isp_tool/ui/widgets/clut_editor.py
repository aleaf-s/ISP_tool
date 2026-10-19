"""HSV parameter wheel and tables; internal LUTs only accelerate image previews."""
import colorsys
from dataclasses import replace
import math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from ...grading.clut import (HSGrid, HUES, SATS, SHAPE,
                            edit_neighborhood,neighbor_weights,apply_clut,build_clut)
from ...grading.hsv_grid import HSVGrid, HUES as HSV_HUES, SATS as HSV_SATS, VALUES, plane_weights
from ..theme import COLORS
from .tooltip import Tooltip
from ..number_format import format_number
from ...grading.hsv_grid import HSVState


class CLUTEditor(ttk.Frame):
    def __init__(self, parent, on_change, error, on_pending=None,on_inspect=None,on_pick=None):
        super().__init__(parent)
        self.on_change=on_change;self.error=error;self.state=HSVState()
        self.on_pending=on_pending or (lambda:None)
        self.on_inspect=on_inspect or (lambda:None)
        self._drag_grid=None;self._drag_preview=None;self.inline=None
        self._reveal_after=None
        self.variables=[tk.StringVar(self,value='0'),tk.StringVar(self,value='0')]
        self.node_label=tk.StringVar(self)
        ttk.Label(self,text='HSV',style='Title.TLabel').pack(anchor='w')
        self.parameter_header=ttk.Frame(self);self.parameter_header.pack(fill='x')
        mode_row=ttk.Frame(self.parameter_header);mode_row.pack(fill='x')
        self.units=tk.StringVar(self)
        units=ttk.Label(mode_row,textvariable=self.units,style='Muted.TLabel')
        units.pack(side='left',padx=8)
        mode_row.bind('<Configure>',lambda e:units.configure(wraplength=max(240,e.width-20)))
        Tooltip(units,'三维 HSV 的 H/S 记录使用样例轴；软件三线性预览，非海思求解器。S=0 编辑锁定；0°/360° 接缝独立保留。')
        pick_row=ttk.Frame(self.parameter_header);pick_row.pack(fill='x',pady=4)
        ttk.Button(pick_row,text='从图像取色定位',command=on_pick or (lambda:None)).pack(side='left')
        self.influence=tk.BooleanVar(self,value=False)
        ttk.Checkbutton(pick_row,text='显示影响范围',variable=self.influence,command=self.inspect_changed).pack(side='left',padx=8)
        self.samples=tk.Canvas(self.parameter_header,height=52,highlightthickness=0,bg=COLORS['panel'])
        self.samples.pack(fill='x');self.samples.bind('<Configure>',lambda e:self.draw_sample())
        font=tkfont.nametofont('TkDefaultFont')
        self.canvas_width=max(320,font.measure('0')*34)
        self.canvas_height=max(280,font.metrics('linespace')*16)
        self.body=ttk.Frame(self);self.body.pack(fill='both',expand=True,pady=6)
        self.side_view=tk.Canvas(self.body,width=340,highlightthickness=0,bg=COLORS['panel'])
        side_scroll=ttk.Scrollbar(self.body,orient='vertical',command=self.side_view.yview)
        side_scroll.pack(side='right',fill='y')
        self.side_view.pack(side='right',fill='y',padx=(10,0))
        self.side_view.configure(yscrollcommand=side_scroll.set)
        self.sidebar=ttk.Frame(self.side_view)
        side_id=self.side_view.create_window(0,0,window=self.sidebar,anchor='nw')
        self.sidebar.bind('<Configure>',lambda e:self.side_view.configure(scrollregion=self.side_view.bbox('all')))
        self.side_view.bind('<Configure>',lambda e:self.side_view.itemconfigure(side_id,width=e.width))
        self.notebook=ttk.Notebook(self.body);self.notebook.pack(side='left',fill='both',expand=True)
        self.wheel=tk.Canvas(self.notebook,width=self.canvas_width,height=self.canvas_height,bg=COLORS['panel_alt'],highlightthickness=0)
        self.notebook.add(self.wheel,text='色轮')
        self.wheel.bind('<Configure>',lambda e:self.draw_wheel())
        self.wheel.bind('<Button-1>',self.wheel_press)
        self.wheel.bind('<B1-Motion>',self.wheel_drag)
        self.wheel.bind('<ButtonRelease-1>',self.wheel_release)
        self.tables={}
        self.cw=max(62,font.measure('-180.00')+18);self.ch=max(27,font.metrics('linespace')+10)
        for component,title in (('dh','Delta Hue'),('ds','Delta Sat')):
            frame=ttk.Frame(self.notebook)
            canvas=tk.Canvas(frame,width=self.canvas_width,height=self.canvas_height,bg='white',highlightthickness=0,takefocus=True)
            ys=ttk.Scrollbar(frame,orient='vertical',command=canvas.yview)
            xs=ttk.Scrollbar(frame,orient='horizontal',command=canvas.xview)
            canvas.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
            canvas.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns');xs.grid(row=1,column=0,sticky='ew')
            frame.columnconfigure(0,weight=1)
            frame.rowconfigure(0,weight=1)
            self.notebook.add(frame,text=title);self.tables[component]=canvas
            canvas.bind('<Button-1>',lambda e,c=component:self.table_press(e,c))
            canvas.bind('<Double-1>',lambda e,c=component:self.open_inline(c))
            canvas.bind('<KeyPress>',lambda e,c=component:self.table_key(e,c))
            canvas.bind('<Control-c>',lambda e,c=component:self.copy_cells(c))
            canvas.bind('<Control-v>',lambda e,c=component:self.paste_cells(c))
            canvas.bind('<MouseWheel>',lambda e,c=canvas:self.scroll_table(e,c))
        self.notebook.bind('<<NotebookTabChanged>>',self.tab_changed)
        self.notebook.bind('<Button-1>',lambda e:None if self.finish_current_input() else 'break')
        self.controls=ttk.Frame(self.sidebar);self.controls.pack(fill='x')
        self.pick_note=tk.StringVar(self)
        strength_row=ttk.Frame(self.controls);strength_row.pack(fill='x',pady=5)
        ttk.Label(strength_row,text='HSV 参数倍率').pack(side='left')
        self.strength_var=tk.StringVar(self,value='1')
        self.strength_box=ttk.Spinbox(strength_row,from_=0,to=2,increment=.1,width=7,
                                    textvariable=self.strength_var,command=self.commit_strength)
        self.strength_box.pack(side='left',padx=8)
        self.strength_box.bind('<Return>',lambda e:self.commit_strength())
        self.strength_box.bind('<FocusOut>',lambda e:self.commit_strength())
        Tooltip(self.strength_box,'0 无 H/S 调整，1 原强度，2 双倍。系数作用于所有亮度层的 ΔHue/ΔSat，应用与导出一致；节点数值仍为基础参数，不会反复累乘。')
        self.strength_var.trace_add('write',self.remember_strength)
        gain_frame=ttk.LabelFrame(self.controls,text='CLUT 生效强度',padding=5)
        gain_frame.pack(fill='x',pady=5)
        self.enabled_var=tk.BooleanVar(self,value=True)
        ttk.Checkbutton(gain_frame,text='Enable',variable=self.enabled_var,command=self.commit_enable).pack(anchor='w')
        self.gain_vars=[];self.gain_sliders=[]
        for i,name in enumerate(('gain_r','gain_g','gain_b')):
            line=ttk.Frame(gain_frame);line.pack(fill='x',pady=2)
            ttk.Label(line,text=name,width=7).pack(side='left')
            var=tk.StringVar(self,value='512');self.gain_vars.append(var)
            box=ttk.Spinbox(line,from_=0,to=4095,increment=1,width=6,textvariable=var,command=self.commit_gains)
            box.pack(side='left',padx=(0,6))
            box.bind('<Return>',lambda e:self.commit_gains())
            box.bind('<FocusOut>',lambda e:self.commit_gains())
            slider=ttk.Scale(line,from_=0,to=4095,command=lambda value,index=i:self.slide_gain(index,value))
            slider.pack(side='left',fill='x',expand=True);self.gain_sliders.append(slider)
            var.trace_add('write',self.remember_gains)
            Tooltip(box,'0～4095 整数；512=1倍，1024=2倍。输出=输入+(LUT输出−输入)×gain/512；只缩放该RGB通道的调整量，点击应用后更新图像。')
        ttk.Label(gain_frame,text='512 = 1× · 1024 = 2×',style='Muted.TLabel').pack(anchor='w')
        note=ttk.Label(gain_frame,text='HSV TXT 不含以上增益，设备端需另填。',style='Muted.TLabel')
        note.pack(anchor='w')
        Tooltip(note,'这些是独立 CLUT Attr 参数；不烘焙进 HSV TXT，避免设备再次施加增益。当前按公开512基准计算，尚未验证PQ Tools V1.1.45实机一致性。')
        brush=ttk.Frame(self.controls);brush.pack(fill='x',pady=4)
        self.radius_var=tk.StringVar(self,value='0');self.smooth_var=tk.StringVar(self,value='1')
        for label,var,choices in (('邻域范围（格）',self.radius_var,tuple(range(7))),
                                  ('平滑强度',self.smooth_var,(0,.25,.5,.75,1))):
            line=ttk.Frame(brush);line.pack(fill='x',pady=3)
            ttk.Label(line,text=label).pack(side='left')
            box=ttk.Combobox(line,textvariable=var,values=choices,state='readonly',width=5)
            box.pack(side='left',padx=(4,10));box.bind('<<ComboboxSelected>>',self.brush_changed)
            Tooltip(box,'0 格为单点。相邻颜色按距离衰减；平滑强度控制过渡曲线。只影响后续单点输入/拖动，粘贴和重置仍精确作用于选区。')
        row=ttk.Frame(self.controls);row.pack(anchor='w',pady=5)
        for i,label in enumerate(('ΔHue °','ΔSat')):
            line=ttk.Frame(row);line.pack(fill='x',pady=3)
            ttk.Label(line,text=label,width=12).pack(side='left',padx=(0,4))
            entry=ttk.Entry(line,textvariable=self.variables[i],width=9,justify='right')
            entry.pack(side='left',padx=(0,8))
            entry.bind('<Return>',lambda e:self.commit_node())
            entry.bind('<FocusIn>',lambda e:self.mark_focus(e.widget))
            entry.bind('<FocusOut>',lambda e:self.focus_commit(e.widget))
            Tooltip(entry,lambda index=i:f'实际值：{self.node_values()[index]:.12g}')
        self.value=tk.StringVar(self,value='.8')
        row=ttk.Frame(self.controls);row.pack(fill='x',pady=5);self.slice_row=row
        self.slice_label=ttk.Label(row,text='色轮 V');self.slice_label.pack(side='left')
        v=ttk.Combobox(row,textvariable=self.value,values=('.25','.5','.8','1'),width=5,state='readonly');self.slice_box=v
        v.pack(side='left',padx=6);v.bind('<<ComboboxSelected>>',self.change_slice)
        Tooltip(v,'编辑以 V=0.5 为基准，H/S 参数自动等量覆盖所有亮度层；可撤销。')
        actions=ttk.Frame(self.controls);actions.pack(fill='x',pady=5)
        ttk.Button(actions,text='重置选区',command=self.reset_selected).pack(side='left')
        ttk.Button(actions,text='重置表',command=self.reset_all).pack(side='left',padx=4)
        history=ttk.Frame(self.controls);history.pack(fill='x',pady=5)
        self.undo=ttk.Button(history,text='撤销',command=lambda:self.travel(False),width=5);self.undo.pack(side='left')
        self.redo=ttk.Button(history,text='重做',command=lambda:self.travel(True),width=5);self.redo.pack(side='left',padx=4)
        self._traces=[(v,v.trace_add('write',self.remember_draft)) for v in self.variables]
        self._rendering=False;self.show_node();self.redraw()

    @property
    def is_hsv(self):
        return isinstance(self.state.grid,HSVGrid)

    @property
    def hues(self):
        return HSV_HUES if self.is_hsv else HUES

    @property
    def sats(self):
        return HSV_SATS if self.is_hsv else SATS

    @property
    def shape(self):
        return (len(self.hues),len(self.sats))

    def plane(self,grid=None,index=None):
        grid=self.state.grid if grid is None else grid
        if not isinstance(grid,HSVGrid):return grid
        index=self.state.slice_index if index is None else index
        cache=getattr(self,'_plane_cache',None)
        if cache is None or cache[0] is not grid or cache[1]!=index:
            self._plane_cache=(grid,index,grid.plane(index))
        return self._plane_cache[2]

    def draft_key(self,r,c,index=None):
        return (self.state.slice_index if index is None else index,r,c) if self.is_hsv else (r,c)

    def patch_grid(self,grid,component,r,c,block,index=None):
        if isinstance(grid,HSVGrid):
            if index not in (None,4):raise ValueError('仅支持编辑 V=0.5 层')
            return grid.patch(component,r,c,block,4).cover_center()
        return grid.patch(component,r,c,block)

    def edit_grid(self,grid,r,c,dh,ds,index=None):
        if isinstance(grid,HSVGrid):
            if index not in (None,4):raise ValueError('仅支持编辑 V=0.5 层')
            return grid.edit(4,r,c,dh,ds,self.state.radius,self.state.smoothness).cover_center()
        return edit_neighborhood(grid,r,c,dh,ds,self.state.radius,self.state.smoothness)

    def sync_format(self):
        self.units.set('H° · S · 编辑自动覆盖全部亮度层；色块显示目标色')
        self.slice_label.configure(text='亮度切片 V' if self.is_hsv else '色轮 V')
        self.slice_box.configure(values=(.5,) if self.is_hsv else ('.25','.5','.8','1'),state='disabled' if self.is_hsv else 'readonly')
        if self.is_hsv:self.state.slice_index=4;self.state.value=.5
        if self.is_hsv:self.slice_row.pack_forget()
        self.value.set(f'{self.state.value:g}')
        for name in ('selected','selection_end'):
            r,c=getattr(self.state,name);setattr(self.state,name,(min(r,self.shape[0]-1),min(c,self.shape[1]-1)))

    def set_state(self,state):
        self.remember_draft();self.close_inline()
        self.state=state;self._drag_grid=self._drag_preview=None
        self.value.set(f'{state.value:g}')
        self.radius_var.set(f'{state.radius:g}');self.smooth_var.set(f'{state.smoothness:g}')
        self.influence.set(state.show_influence)
        self.notebook.select(('色轮','Delta Hue','Delta Sat').index(state.tab))
        self.show_node();self.redraw()

    def mark_focus(self,widget):
        widget.clut_context=(self.state,self.state.selected,self.state.slice_index)

    def node_values(self):
        r,c=self.state.selected;k=r*self.shape[1]+c
        p=self.plane();return p.dh[k],p.ds[k]

    def node_text(self):
        # Compact display only. Unedited fields retain the full model precision.
        return self.format_node(self.node_values())

    @staticmethod
    def format_node(values):
        return tuple(format_number(v,d) for v,d in zip(values,(1,3)))

    def focus_commit(self,widget):
        context=getattr(widget,'clut_context',None)
        if context and context[0] is self.state and context[1]==self.state.selected and context[2]==self.state.slice_index and self.winfo_ismapped():
            if self.commit_node() and widget is self.inline:self.close_inline()

    def finish_current_input(self):
        """Commit before UI navigation changes selection; never apply the image."""
        self.remember_draft()
        if self.draft_key(*self.state.selected) in self.state.drafts and not self.commit_node():return False
        self.close_inline()
        return True

    def remember_draft(self,*_):
        if getattr(self,'_rendering',False):return
        r,c=self.state.selected;k=r*self.shape[1]+c
        values=tuple(v.get() for v in self.variables)
        canonical=self.node_text()
        if values!=canonical:self.state.drafts[self.draft_key(r,c)]=values
        else:self.state.drafts.pop(self.draft_key(r,c),None)
        self.on_pending()

    def show_node(self):
        self.sync_format()
        self._rendering=True
        draft=getattr(self.state,'strength_draft',None)
        self.strength_var.set(draft if draft is not None else format_number(getattr(self.state.grid,'strength',1),2))
        self.enabled_var.set(getattr(self.state.grid,'enabled',True))
        gains=getattr(self.state.grid,'gains',(512,512,512))
        draft=self.state.gain_draft
        for i,(var,slider,gain) in enumerate(zip(self.gain_vars,self.gain_sliders,gains)):
            var.set(draft[i] if draft is not None else str(gain));slider.set(gain)
        r,c=self.state.selected;k=r*self.shape[1]+c
        values=self.state.drafts.get(self.draft_key(r,c),self.node_text())
        for v,text in zip(self.variables,values):v.set(text)
        self.node_label.set(f'H {self.hues[r]:g}° · S {self.sats[c]:g} · 第 {r+1} 行 / 第 {c+1} 列' + (f' · V {VALUES[self.state.slice_index]:g}' if self.is_hsv else '') + (' · 中性轴锁定' if c==0 else ''))
        dh,ds=self.node_values()
        self.node_label.set(self.node_label.get()+f' → H {format_number(self.hues[r]+dh,1)}° · S {format_number(self.sats[c]+ds,3)}')
        self._rendering=False

    def select_node(self,row,column,extend=False):
        self.remember_draft();self.close_inline()
        row=max(0,min(self.shape[0]-1,row));column=max(0,min(self.shape[1]-1,column))
        if not extend:self.state.selected=(row,column)
        self.state.selection_end=(row,column)
        self.show_node();self.redraw()
        for canvas in self.tables.values():
            canvas.yview_moveto(max(0,(row-3)/(self.shape[0]+1)));canvas.xview_moveto(max(0,(column-2)/(self.shape[1]+1)))

    def locate_sample(self,row,column):
        # Keep a previously selected delta table; the wheel defaults to Hue.
        tab='Delta Sat' if self.state.tab=='Delta Sat' else 'Delta Hue'
        self.select_node(row,column)
        self.state.tab=tab;self.notebook.select(2 if tab=='Delta Sat' else 1)
        if self._reveal_after is not None:self.after_cancel(self._reveal_after)
        state=self.state;selected=state.selected
        def reveal():
            self._reveal_after=None
            if self.state is not state or self.state.selected!=selected:return
            r,c=selected
            for canvas in self.tables.values():
                canvas.yview_moveto(max(0,((r+1.5)*self.ch-canvas.winfo_height()/2)/((self.shape[0]+1)*self.ch)))
                canvas.xview_moveto(max(0,((c+1.5)*self.cw-canvas.winfo_width()/2)/((self.shape[1]+1)*self.cw)))
        self._reveal_after=self.after_idle(reveal)

    def brush_changed(self,event=None):
        radius,smooth=float(self.radius_var.get()),float(self.smooth_var.get())
        (plane_weights if self.is_hsv else neighbor_weights)(*self.state.selected,radius,smooth)
        self.state.radius=radius;self.state.smoothness=smooth
        self.redraw()

    def inspect_changed(self):
        self.state.show_influence=self.influence.get();self.on_inspect()

    def draw_sample(self):
        self.samples.delete('all')
        font=tkfont.nametofont('TkDefaultFont');line=font.metrics('linespace')
        stacked=self.samples.winfo_width()<2*(font.measure('H 359.9° · S 0.999 · V 0.999')+55)
        row_height=max(52,line*2+12)
        self.samples.configure(height=row_height*(2 if stacked and self.state.sample_rgb is not None else 1))
        self.samples.pack(fill='x')
        if self.state.sample_rgb is None:
            r,c=self.state.selected;p=self.plane(self._drag_preview or self.state.grid);k=r*self.shape[1]+c
            node_colors=((self.hues[r],self.sats[c],self.state.value),
                         (self.hues[r]+p.dh[k],self.sats[c]+p.ds[k],self.state.value))
            self.samples.configure(height=row_height*(2 if stacked else 1))
            for i,(h,s,v) in enumerate(node_colors):
                x=4 if stacked or i==0 else self.samples.winfo_width()/2;y=row_height*i if stacked else 0
                self.samples.create_rectangle(x,y+6,x+34,y+row_height-6,fill=self.color(h,s,v),outline=COLORS['border'])
                label='节点原色' if i==0 else '节点目标色 · H/S'
                self.samples.create_text(x+42,y+4,anchor='nw',text=f'{label}\nH {format_number(h,1)}° · S {format_number(s,3)} · V {format_number(v,3)}',fill=COLORS['foreground'])
            return
        source=self.state.sample_rgb
        if self.is_hsv and not self.state.grid.preview_supported:
            self.samples.create_text(4,20,anchor='w',text='非零第三字段未确认：仅编辑/保存，不能计算目标色',fill=COLORS['muted']);return
        import numpy as np
        target=apply_clut(np.asarray(source,np.float32).reshape(1,1,3),build_clut(self._drag_preview or self.state.grid))[0,0]
        for x,y,color,label in ((4,0,source,'原色 HSV · 5×5'),
                (4 if stacked else self.samples.winfo_width()/2,row_height if stacked else 0,target,'目标色 HSV · 草稿')):
            rgb=tuple(round(float(v)*255) for v in color)
            h,s,v=colorsys.rgb_to_hsv(*map(float,color))
            hue=f'{format_number(h*360,1)}°' if s>1e-6 and v>1e-6 else '—'
            values=f'H {hue} · S {format_number(s,3)} · V {format_number(v,3)}'
            self.samples.create_rectangle(x,y+6,x+34,y+row_height-6,fill='#%02x%02x%02x'%rgb,outline=COLORS['border'])
            self.samples.create_text(x+42,y+4,anchor='nw',text=f'{label}\n{values}',fill=COLORS['foreground'],font='TkDefaultFont')

    def commit_node(self):
        try:
            dh,ds=(old if var.get()==shown else float(var.get())
                   for var,shown,old in zip(self.variables,self.node_text(),self.node_values()))
            r,c=self.state.selected
            # A focus-only commit must not flatten an untouched imported file.
            grid=self.state.grid if (dh,ds)==self.node_values() else self.edit_grid(self.state.grid,r,c,dh,ds)
            self.state.drafts.pop(self.draft_key(r,c),None);self.error.set('')
            if grid!=self.state.grid:self.on_change(grid,True)
            self.show_node();self.redraw()
            return True
        except ValueError as exc:
            self.error.set(str(exc));self.remember_draft();return False

    def commit_all(self):
        """Validate every text draft atomically before explicit Apply."""
        if self._drag_grid is not None:
            self.error.set('请先结束色轮拖动');return False
        self.remember_draft();grid=self.state.grid;explicit=[]
        try:
            if self.is_hsv:
                grid=replace(grid,strength=float(self.strength_var.get()),gains=self.read_gains())
            for key,texts in self.state.drafts.items():
                index,r,c=key if len(key)==3 else (None,*key)
                k=r*self.shape[1]+c
                p=self.plane(self.state.grid,index);old=(p.dh[k],p.ds[k])
                shown=self.format_node(old)
                dh,ds=(v if text==display else float(text)
                       for text,display,v in zip(texts,shown,old))
                grid=self.edit_grid(grid,r,c,dh,ds,index)
                explicit.append((index,r,c,dh,ds))
            # Neighboring brushes may overlap, but explicitly typed centers win.
            for index,r,c,dh,ds in explicit:
                grid=self.patch_grid(self.patch_grid(grid,'dh',r,c,[[dh]],index),'ds',r,c,[[ds]],index)
        except ValueError as exc:
            self.error.set(str(exc))
            return False
        self.state.drafts.clear();self.state.strength_draft=None;self.state.gain_draft=None
        if grid!=self.state.grid:self.on_change(grid,True)
        self.close_inline();self.show_node();self.redraw();self.on_pending()
        return True

    def remember_strength(self,*_):
        if getattr(self,'_rendering',False):return
        text=self.strength_var.get()
        self.state.strength_draft=None if text==format_number(getattr(self.state.grid,'strength',1),2) else text
        self.on_pending()

    def commit_strength(self):
        if not self.is_hsv:return True
        try:grid=replace(self.state.grid,strength=float(self.strength_var.get()))
        except ValueError:
            self.error.set('整体强度请输入 0～2 的有限数字');return False
        self.state.strength_draft=None
        if grid!=self.state.grid:self.on_change(grid,True)
        self.error.set('');self.show_node();self.redraw();self.on_pending()
        return True

    def read_gains(self):
        try:
            gains=tuple(int(var.get()) for var in self.gain_vars)
            if any(not 0<=value<=4095 for value in gains):raise ValueError()
            return gains
        except ValueError:raise ValueError('gain_r / gain_g / gain_b 请输入 0～4095 的整数')

    def remember_gains(self,*_):
        if getattr(self,'_rendering',False):return
        values=tuple(var.get() for var in self.gain_vars)
        canonical=tuple(str(v) for v in getattr(self.state.grid,'gains',(512,512,512)))
        self.state.gain_draft=None if values==canonical else values
        self.on_pending()

    def commit_gains(self):
        if not self.is_hsv:return True
        try:grid=replace(self.state.grid,gains=self.read_gains())
        except ValueError as exc:self.error.set(str(exc));return False
        self.state.gain_draft=None
        if grid!=self.state.grid:self.on_change(grid,True)
        self.error.set('');self.show_node();self.redraw();self.on_pending()
        return True

    def slide_gain(self,index,value):
        if getattr(self,'_rendering',False):return
        self.gain_vars[index].set(str(round(float(value))))
        self.commit_gains()

    def commit_enable(self):
        if not self.is_hsv:return
        self.on_change(replace(self.state.grid,enabled=self.enabled_var.get()),True)
        self.show_node();self.redraw();self.on_pending()

    def bounds(self):
        r,c=self.state.selected;rr,cc=self.state.selection_end
        return min(r,rr),min(c,cc),max(r,rr),max(c,cc)

    def reset_selected(self):
        r,c,rr,cc=self.bounds();a=[0.]*(cc-c+1);block=[a]*(rr-r+1)
        grid=self.patch_grid(self.patch_grid(self.state.grid,'dh',r,c,block),'ds',r,c,block)
        for row in range(r,rr+1):
            for col in range(c,cc+1):self.state.drafts.pop(self.draft_key(row,col),None)
        self.on_change(grid,True);self.error.set('');self.show_node();self.redraw()

    def reset_all(self):
        self.state.drafts.clear();self.on_change(self.state.grid.reset() if self.is_hsv else HSGrid(base_words=self.state.grid.base_words),True)
        self.error.set('');self.show_node();self.redraw()

    def travel(self,redo):
        if self.state.travel(redo):
            self.on_change(self.state.grid,True);self.error.set('');self.show_node();self.redraw()

    def change_slice(self,event=None):
        value=float(self.value.get())
        if not self.finish_current_input():self.value.set(f'{self.state.value:g}');return
        if self.is_hsv:self.state.slice_index=4;value=.5
        self.state.value=value;self.show_node();self.redraw()

    def tab_changed(self,event=None):
        self.close_inline()
        if self.notebook.select():self.state.tab=self.notebook.tab(self.notebook.select(),'text')

    def redraw(self):
        self.draw_wheel()
        for c in self.tables:self.draw_table(c)
        self.undo.configure(state='normal' if self.state.undo_stack else 'disabled')
        self.redo.configure(state='normal' if self.state.redo_stack else 'disabled')
        self.draw_sample();self.on_inspect()

    @staticmethod
    def color(h,s,v):
        rgb=colorsys.hsv_to_rgb((h%360)/360,max(0,min(1,s)),v)
        return '#%02x%02x%02x'%tuple(round(x*255) for x in rgb)

    def wheel_geometry(self):
        if self._drag_grid is not None and hasattr(self,'_drag_geometry'):return self._drag_geometry
        w=max(260,self.wheel.winfo_width());h=max(250,self.wheel.winfo_height())
        return w/2,h/2,min(w,h)/2-15

    def wheel_smax(self):
        if self._drag_grid is not None and hasattr(self,'_drag_scale'):return self._drag_scale
        grid=self._drag_preview or self.state.grid
        cached=getattr(self,'_wheel_scale',None)
        if cached is None or cached[0] is not grid or cached[1]!=self.state.slice_index:
            p=self.plane(grid)
            scale=max(self.sats[-1],max(self.sats[c]+p.ds[r*self.shape[1]+c] for r in range(self.shape[0]) for c in range(self.shape[1])))
            self._wheel_scale=(grid,self.state.slice_index,scale)
        return self._wheel_scale[2]

    def point_xy(self,r,c,grid):
        cx,cy,radius=self.wheel_geometry();k=r*self.shape[1]+c
        p=self.plane(grid);angle=math.radians(self.hues[r]+p.dh[k]);sat=max(0,self.sats[c]+p.ds[k])/self.wheel_smax()
        return cx+math.cos(angle)*sat*radius,cy-math.sin(angle)*sat*radius

    def draw_wheel(self):
        self.wheel.delete('all');cx,cy,radius=self.wheel_geometry()
        grid=self._drag_preview or self.state.grid
        # Deform every shared mesh vertex with its target node, including while dragging.
        p=self.plane(grid)
        xy={(r,c):self.point_xy(r,c,grid) for r in range(self.shape[0]) for c in range(self.shape[1])}
        for r,h in enumerate(self.hues[:-1] if self.is_hsv else self.hues):
            rr=(r+1)%self.shape[0]
            for c in range(len(self.sats)-1):
                corners=((r,c),(rr,c),(rr,c+1),(r,c+1))
                points=[v for corner in corners for v in xy[corner]]
                dh=sum(p.dh[a*self.shape[1]+b] for a,b in corners)/4
                ds=sum(p.ds[a*self.shape[1]+b] for a,b in corners)/4
                self.wheel.create_polygon(*points,fill=self.color(h+7.5+dh,(self.sats[c]+self.sats[c+1])/2+ds,self.state.value),outline='#e0e3e6',width=2,tags=f'mesh-{r}-{c}')
        for r in range(len(self.hues)):
            for c in range(1,len(self.sats)):
                x,y=xy[r,c];angle=math.radians(self.hues[r])
                length=self.sats[c]*radius/self.wheel_smax()
                ox,oy=cx+math.cos(angle)*length,cy-math.sin(angle)*length
                self.wheel.create_line(ox,oy,x,y,fill='white',dash=(2,2))
                self.wheel.create_oval(ox-1,oy-1,ox+1,oy+1,fill='#eeeeee',outline='')
                selected=(r,c)==self.state.selected
                size=8 if selected else 6
                self.wheel.create_oval(x-size,y-size,x+size,y+size,fill=self.color(self.hues[r]+p.dh[r*self.shape[1]+c],self.sats[c]+p.ds[r*self.shape[1]+c],self.state.value),outline=COLORS['accent'] if selected else '#202830',width=3 if selected else 2,tags=f'target-node-{r}-{c}')
        self.wheel.tag_raise(f'target-node-{self.state.selected[0]}-{self.state.selected[1]}')
        self.wheel.create_oval(cx-4,cy-4,cx+4,cy+4,fill='#ddd',outline='#555')

    def wheel_press(self,event):
        if not self.finish_current_input():return
        grid=self.state.grid
        nearest=min((round((event.x-self.point_xy(r,c,grid)[0])**2+(event.y-self.point_xy(r,c,grid)[1])**2,6),(r,c)!=self.state.selected,r,c)
                    for r in range(self.shape[0]) for c in range(1,self.shape[1]))
        if nearest[0]>14**2:return
        self.select_node(nearest[2],nearest[3])
        self._drag_geometry=self.wheel_geometry();self._drag_scale=self.wheel_smax()
        x,y=self.point_xy(*self.state.selected,grid)
        self._drag_offset=(x-event.x,y-event.y)
        self._drag_grid=grid

    def wheel_drag(self,event):
        if self._drag_grid is None:return
        cx,cy,radius=self.wheel_geometry();r,c=self.state.selected
        x=event.x+self._drag_offset[0];y=event.y+self._drag_offset[1]
        h=math.degrees(math.atan2(cy-y,x-cx))%360
        s=max(0,math.hypot(x-cx,y-cy)/radius*self.wheel_smax())
        delta=(h-self.hues[r]+180)%360-180
        try:
            self._drag_preview=self.edit_grid(self._drag_grid,r,c,delta,s-self.sats[c])
        except ValueError as exc:
            self.error.set(str(exc));return
        self.on_change(self._drag_preview,False);self.draw_wheel()
        for component in self.tables:self.draw_table(component)
        self.draw_sample()

    def wheel_release(self,event=None):
        if self._drag_grid is None:return
        grid=self._drag_preview
        self._drag_grid=self._drag_preview=None
        if grid is not None:self.on_change(grid,True)
        self.show_node();self.redraw()

    def draw_table(self,component):
        canvas=self.tables[component];canvas.delete('all');cw,ch=self.cw,self.ch
        plane=self.plane(self._drag_preview or self.state.grid)
        values=getattr(plane,component);r0,c0,r1,c1=self.bounds()
        for c,s in enumerate(self.sats):canvas.create_text((c+1.5)*cw,ch/2,text=f'{s:g}')
        for r,h in enumerate(self.hues):
            canvas.create_text(cw/2,(r+1.5)*ch,text=f'{h:g}°')
            for c,s in enumerate(self.sats):
                x,y=(c+1)*cw,(r+1)*ch
                k=r*self.shape[1]+c;th=h+plane.dh[k];ts=s+plane.ds[k]
                fill=self.color(th,ts,self.state.value)
                active=r0<=r<=r1 and c0<=c<=c1
                canvas.create_rectangle(x,y,x+cw,y+ch,fill=fill,outline=COLORS['accent'] if active else '#aaa',width=3 if active else 1,tags=f'target-cell-{r}-{c}')
                canvas.create_rectangle(x+1,y+1,x+5,y+ch-1,fill=self.color(h,s,self.state.value),outline='',tags=f'original-cell-{r}-{c}')
                rgb=colorsys.hsv_to_rgb((th%360)/360,max(0,min(1,ts)),self.state.value)
                fg='#17212b' if sum(a*b for a,b in zip(rgb,(.2126,.7152,.0722)))>.52 else 'white'
                canvas.create_text(x+cw/2,y+ch/2,text=format_number(values[r*self.shape[1]+c],1 if component=='dh' else 3),fill=fg)
        canvas.configure(scrollregion=(0,0,cw*(self.shape[1]+1),ch*(self.shape[0]+1)))
        r,c=self.state.selected;x,y=(c+1)*cw,(r+1)*ch
        canvas.create_rectangle(x+2,y+2,x+cw-2,y+ch-2,outline='white',width=5,tags='selected-node')
        canvas.create_rectangle(x+2,y+2,x+cw-2,y+ch-2,outline=COLORS['accent'],width=3,tags='selected-node')

    def table_press(self,event,component):
        if not self.finish_current_input():return 'break'
        canvas=self.tables[component];canvas.focus_set()
        r=int(canvas.canvasy(event.y)//self.ch)-1;c=int(canvas.canvasx(event.x)//self.cw)-1
        if 0<=r<self.shape[0] and 0<=c<self.shape[1]:self.select_node(r,c,bool(event.state&1))
        return 'break'

    def table_key(self,event,component):
        r,c=self.state.selection_end
        steps={'Left':(0,-1),'Right':(0,1),'Up':(-1,0),'Down':(1,0)}
        if event.keysym in steps:
            if not self.finish_current_input():return 'break'
            dr,dc=steps[event.keysym];self.select_node(r+dr,c+dc,bool(event.state&1))
            self.tables[component].yview_moveto(max(0,(self.state.selection_end[0]-3)/(self.shape[0]+1)))
            self.tables[component].xview_moveto(max(0,(self.state.selection_end[1]-2)/(self.shape[1]+1)))
        elif event.keysym in ('Return','F2'):self.open_inline(component)
        elif event.char in '0123456789-+.':
            if event.char and not event.state&4:self.open_inline(component,event.char)
        return 'break'

    def open_inline(self,component,text=None):
        if not self.finish_current_input():return
        r,c=self.state.selected;canvas=self.tables[component]
        index=0 if component=='dh' else 1
        entry=ttk.Entry(canvas,textvariable=self.variables[index],width=7,justify='right')
        entry.place(x=(c+1)*self.cw-canvas.canvasx(0),y=(r+1)*self.ch-canvas.canvasy(0),width=self.cw,height=self.ch)
        self.inline=entry
        self.mark_focus(entry)
        if text is not None:self.variables[index].set(text)
        entry.focus_set();entry.icursor('end')
        if text is None:entry.selection_range(0,'end')
        entry.bind('<Return>',lambda e:self.finish_inline())
        entry.bind('<FocusOut>',lambda e:self.focus_commit(e.widget))
        entry.bind('<Tab>',lambda e:self.advance_inline(component,1))
        entry.bind('<Shift-Tab>',lambda e:self.advance_inline(component,-1))
        entry.bind('<Escape>',lambda e:self.close_inline())

    def finish_inline(self):
        if self.commit_node():self.close_inline()
        return 'break'

    def advance_inline(self,component,direction):
        if not self.finish_current_input():return 'break'
        r,c=self.state.selected
        columns=self.shape[1]-1
        index=max(0,min(self.shape[0]*columns-1,r*columns+max(0,c-1)+direction))
        self.select_node(index//columns,index%columns+1);self.open_inline(component)
        return 'break'

    def close_inline(self):
        if self.inline is not None:
            widget,self.inline=self.inline,None
            widget.unbind('<FocusOut>');widget.destroy()

    def copy_cells(self,component):
        r,c,rr,cc=self.bounds();values=getattr(self.plane(),component)
        text='\n'.join('\t'.join(f'{values[row*self.shape[1]+col]:g}' for col in range(c,cc+1)) for row in range(r,rr+1))
        self.clipboard_clear();self.clipboard_append(text);return 'break'

    def paste_cells(self,component,text=None):
        try:
            if self.state.drafts:raise ValueError('请先提交或重置未完成的数字输入')
            text=self.clipboard_get() if text is None else text
            rows=[[float(v) for v in row.split()] for row in text.strip().splitlines()]
            if not rows or not rows[0] or any(len(row)!=len(rows[0]) for row in rows):raise ValueError('需要矩形 TSV 数字区域')
            r,c,_,_=self.bounds();grid=self.patch_grid(self.state.grid,component,r,c,rows)
            self.on_change(grid,True);self.error.set('');self.show_node();self.redraw()
        except (ValueError,tk.TclError) as exc:self.error.set(str(exc))
        return 'break'

    @staticmethod
    def scroll_table(event,canvas):
        canvas.yview_scroll(-3 if event.delta>0 else 3,'units');return 'break'

    def destroy(self):
        if self._reveal_after is not None:self.after_cancel(self._reveal_after)
        self.close_inline()
        for v,trace in self._traces:v.trace_remove('write',trace)
        super().destroy()
