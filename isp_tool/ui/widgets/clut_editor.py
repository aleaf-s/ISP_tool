"""Compact HS wheel and editable delta tables backed by one CLUTState."""
import colorsys
import math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from ...grading.clut import (CLUTState, HSGrid, HUES, SATS, SHAPE,
                            edit_neighborhood,neighbor_weights,apply_clut,build_clut)
from ..theme import COLORS
from .tooltip import Tooltip
from ..number_format import format_number


class CLUTEditor(ttk.Frame):
    def __init__(self, parent, on_change, error, on_pending=None,on_inspect=None,on_pick=None):
        super().__init__(parent)
        self.on_change=on_change;self.error=error;self.state=CLUTState()
        self.on_pending=on_pending or (lambda:None)
        self.on_inspect=on_inspect or (lambda:None)
        self._drag_grid=None;self._drag_preview=None;self.inline=None
        self._reveal_after=None
        self.variables=[tk.StringVar(self,value='0'),tk.StringVar(self,value='0')]
        self.node_label=tk.StringVar(self)
        ttk.Label(self,text='CLUT',style='Title.TLabel').pack(anchor='w')
        units=ttk.Label(self,text='H° · S/V 0–1 · 软件约定',style='Muted.TLabel')
        units.pack(anchor='w')
        Tooltip(units,'Sat 为加法偏移；当前不是海思扩展 HSV 模型。S=0 中性轴锁定。')
        pick_row=ttk.Frame(self);pick_row.pack(fill='x',pady=4)
        ttk.Button(pick_row,text='从图像取色定位',command=on_pick or (lambda:None)).pack(side='left')
        self.influence=tk.BooleanVar(self,value=False)
        ttk.Checkbutton(pick_row,text='显示影响范围',variable=self.influence,command=self.inspect_changed).pack(side='left',padx=8)
        self.samples=tk.Canvas(self,height=52,highlightthickness=0,bg=COLORS['panel'])
        self.samples.pack(fill='x');self.samples.bind('<Configure>',lambda e:self.draw_sample())
        font=tkfont.nametofont('TkDefaultFont')
        self.canvas_width=max(320,font.measure('0')*34)
        self.canvas_height=max(280,font.metrics('linespace')*16)
        self.notebook=ttk.Notebook(self);self.notebook.pack(fill='both',expand=True,pady=6)
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
        ttk.Label(self,textvariable=self.node_label).pack(anchor='w')
        brush=ttk.Frame(self);brush.pack(fill='x',pady=4)
        self.radius_var=tk.StringVar(self,value='0');self.smooth_var=tk.StringVar(self,value='1')
        for label,var,choices in (('邻域范围（格）',self.radius_var,tuple(range(7))),
                                  ('平滑强度',self.smooth_var,(0,.25,.5,.75,1))):
            ttk.Label(brush,text=label).pack(side='left')
            box=ttk.Combobox(brush,textvariable=var,values=choices,state='readonly',width=5)
            box.pack(side='left',padx=(4,10));box.bind('<<ComboboxSelected>>',self.brush_changed)
            Tooltip(box,'0 格为单点。相邻颜色按距离衰减；平滑强度控制过渡曲线。只影响后续单点输入/拖动，粘贴和重置仍精确作用于选区。')
        row=ttk.Frame(self);row.pack(anchor='w',pady=5)
        for i,label in enumerate(('ΔHue °','ΔSat')):
            ttk.Label(row,text=label).pack(side='left',padx=(0,4))
            entry=ttk.Entry(row,textvariable=self.variables[i],width=9,justify='right')
            entry.pack(side='left',padx=(0,8))
            entry.bind('<Return>',lambda e:self.commit_node())
            entry.bind('<FocusIn>',lambda e:self.mark_focus(e.widget))
            entry.bind('<FocusOut>',lambda e:self.focus_commit(e.widget))
            Tooltip(entry,lambda index=i:f'实际值：{self.node_values()[index]:.12g}')
        self.value=tk.StringVar(self,value='.8')
        row=ttk.Frame(self);row.pack(anchor='w',pady=3)
        ttk.Label(row,text='色轮 V').pack(side='left')
        v=ttk.Combobox(row,textvariable=self.value,values=('.25','.5','.8','1'),width=5,state='readonly')
        v.pack(side='left',padx=6);v.bind('<<ComboboxSelected>>',self.change_slice)
        Tooltip(v,'仅改变色轮显示亮度，不改变图像或 CLUT。')
        actions=ttk.Frame(self);actions.pack(fill='x',pady=5)
        ttk.Button(actions,text='重置选区',command=self.reset_selected).pack(side='left')
        ttk.Button(actions,text='重置表',command=self.reset_all).pack(side='left',padx=4)
        history=ttk.Frame(self);history.pack(fill='x',pady=3)
        self.undo=ttk.Button(history,text='撤销',command=lambda:self.travel(False),width=5);self.undo.pack(side='left')
        self.redo=ttk.Button(history,text='重做',command=lambda:self.travel(True),width=5);self.redo.pack(side='left',padx=4)
        ttk.Label(self,textvariable=self.error,style='Error.TLabel',wraplength=320).pack(fill='x')
        self._traces=[(v,v.trace_add('write',self.remember_draft)) for v in self.variables]
        self._rendering=False;self.show_node();self.redraw()

    def set_state(self,state):
        self.remember_draft();self.close_inline()
        self.state=state;self._drag_grid=self._drag_preview=None
        self.value.set(f'{state.value:g}')
        self.radius_var.set(f'{state.radius:g}');self.smooth_var.set(f'{state.smoothness:g}')
        self.influence.set(state.show_influence)
        self.notebook.select(('色轮','Delta Hue','Delta Sat').index(state.tab))
        self.show_node();self.redraw()

    def mark_focus(self,widget):
        widget.clut_context=(self.state,self.state.selected)

    def node_values(self):
        r,c=self.state.selected;k=r*SHAPE[1]+c
        return self.state.grid.dh[k],self.state.grid.ds[k]

    def node_text(self):
        # Compact display only. Unedited fields retain the full model precision.
        return self.format_node(self.node_values())

    @staticmethod
    def format_node(values):
        return tuple(format_number(v,d) for v,d in zip(values,(1,3)))

    def focus_commit(self,widget):
        context=getattr(widget,'clut_context',None)
        if context and context[0] is self.state and context[1]==self.state.selected and self.winfo_ismapped():
            if self.commit_node() and widget is self.inline:self.close_inline()

    def finish_current_input(self):
        """Commit before UI navigation changes selection; never apply the image."""
        self.remember_draft()
        if self.state.selected in self.state.drafts and not self.commit_node():return False
        self.close_inline()
        return True

    def remember_draft(self,*_):
        if getattr(self,'_rendering',False):return
        r,c=self.state.selected;k=r*SHAPE[1]+c
        values=tuple(v.get() for v in self.variables)
        canonical=self.node_text()
        if values!=canonical:self.state.drafts[(r,c)]=values
        else:self.state.drafts.pop((r,c),None)
        self.on_pending()

    def show_node(self):
        self._rendering=True
        r,c=self.state.selected;k=r*SHAPE[1]+c
        values=self.state.drafts.get((r,c),self.node_text())
        for v,text in zip(self.variables,values):v.set(text)
        self.node_label.set(f'H {HUES[r]:g}° · S {SATS[c]:g} · 第 {r+1} 行 / 第 {c+1} 列' + (' · 中性轴锁定' if c==0 else ''))
        self._rendering=False

    def select_node(self,row,column,extend=False):
        self.remember_draft();self.close_inline()
        row=max(0,min(SHAPE[0]-1,row));column=max(0,min(SHAPE[1]-1,column))
        if not extend:self.state.selected=(row,column)
        self.state.selection_end=(row,column)
        self.show_node();self.redraw()
        for canvas in self.tables.values():
            canvas.yview_moveto(max(0,(row-3)/25));canvas.xview_moveto(max(0,(column-2)/10))

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
                canvas.yview_moveto(max(0,((r+1.5)*self.ch-canvas.winfo_height()/2)/(25*self.ch)))
                canvas.xview_moveto(max(0,((c+1.5)*self.cw-canvas.winfo_width()/2)/(10*self.cw)))
        self._reveal_after=self.after_idle(reveal)

    def brush_changed(self,event=None):
        radius,smooth=float(self.radius_var.get()),float(self.smooth_var.get())
        neighbor_weights(*self.state.selected,radius,smooth)
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
        if self.state.sample_rgb is None:
            self.samples.create_text(4,20,anchor='w',text='从原图取色后显示原色与目标色',fill=COLORS['muted']);return
        source=self.state.sample_rgb
        import numpy as np
        target=apply_clut(np.asarray(source,np.float32).reshape(1,1,3),build_clut(self.state.grid))[0,0]
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
            grid=edit_neighborhood(self.state.grid,r,c,dh,ds,self.state.radius,self.state.smoothness)
            self.state.drafts.pop((r,c),None);self.error.set('')
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
            for (r,c),texts in self.state.drafts.items():
                k=r*SHAPE[1]+c
                old=(self.state.grid.dh[k],self.state.grid.ds[k])
                shown=self.format_node(old)
                dh,ds=(v if text==display else float(text)
                       for text,display,v in zip(texts,shown,old))
                grid=edit_neighborhood(grid,r,c,dh,ds,self.state.radius,self.state.smoothness)
                explicit.append((r,c,dh,ds))
            # Neighboring brushes may overlap, but explicitly typed centers win.
            for r,c,dh,ds in explicit:
                grid=grid.patch('dh',r,c,[[dh]]).patch('ds',r,c,[[ds]])
        except ValueError as exc:
            self.error.set(f'H {HUES[r]:g}° / S {SATS[c]:g}: {exc}')
            return False
        self.state.drafts.clear()
        if grid!=self.state.grid:self.on_change(grid,True)
        self.close_inline();self.show_node();self.redraw();self.on_pending()
        return True

    def bounds(self):
        r,c=self.state.selected;rr,cc=self.state.selection_end
        return min(r,rr),min(c,cc),max(r,rr),max(c,cc)

    def reset_selected(self):
        r,c,rr,cc=self.bounds();a=[0.]*(cc-c+1);block=[a]*(rr-r+1)
        grid=self.state.grid.patch('dh',r,c,block).patch('ds',r,c,block)
        for row in range(r,rr+1):
            for col in range(c,cc+1):self.state.drafts.pop((row,col),None)
        self.on_change(grid,True);self.error.set('');self.show_node();self.redraw()

    def reset_all(self):
        self.state.drafts.clear();self.on_change(HSGrid(base_words=self.state.grid.base_words),True)
        self.error.set('');self.show_node();self.redraw()

    def travel(self,redo):
        if self.state.travel(redo):
            self.on_change(self.state.grid,True);self.error.set('');self.show_node();self.redraw()

    def change_slice(self,event=None):
        self.state.value=float(self.value.get());self.redraw()

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
        w=max(260,self.wheel.winfo_width());h=max(250,self.wheel.winfo_height())
        return w/2,h/2,min(w,h)/2-15

    def point_xy(self,r,c,grid):
        cx,cy,radius=self.wheel_geometry();k=r*SHAPE[1]+c
        angle=math.radians(HUES[r]+grid.dh[k]);sat=max(0,min(1,SATS[c]+grid.ds[k]))
        return cx+math.cos(angle)*sat*radius,cy-math.sin(angle)*sat*radius

    def draw_wheel(self):
        self.wheel.delete('all');cx,cy,radius=self.wheel_geometry()
        grid=self._drag_preview or self.state.grid
        identity=HSGrid()
        # Small, fixed mesh; no full-size bitmap computation on UI events.
        for r,h in enumerate(HUES):
            for c in range(len(SATS)-1):
                points=[]
                for hh,ss in ((h,SATS[c]),(h+15,SATS[c]),(h+15,SATS[c+1]),(h,SATS[c+1])):
                    angle=math.radians(hh);points.extend((cx+math.cos(angle)*ss*radius,cy-math.sin(angle)*ss*radius))
                self.wheel.create_polygon(*points,fill=self.color(h+7.5,(SATS[c]+SATS[c+1])/2,self.state.value),outline='#b9c0c6')
        for r in range(len(HUES)):
            for c in range(1,len(SATS)):
                x,y=self.point_xy(r,c,grid);ox,oy=self.point_xy(r,c,identity)
                self.wheel.create_line(ox,oy,x,y,fill='white',dash=(2,2))
                self.wheel.create_oval(ox-1,oy-1,ox+1,oy+1,fill='#eeeeee',outline='')
                selected=(r,c)==self.state.selected
                self.wheel.create_oval(x-4,y-4,x+4,y+4,fill='#ffffff' if selected else '#bfc7cf',outline=COLORS['accent'] if selected else '#343a40',width=2 if selected else 1)
        self.wheel.create_oval(cx-4,cy-4,cx+4,cy+4,fill='#ddd',outline='#555')

    def wheel_press(self,event):
        if not self.finish_current_input():return
        grid=self.state.grid
        nearest=min(((event.x-self.point_xy(r,c,grid)[0])**2+(event.y-self.point_xy(r,c,grid)[1])**2,r,c)
                    for r in range(24) for c in range(1,9))
        if nearest[0]>14**2:return
        self.select_node(nearest[1],nearest[2]);self._drag_grid=grid

    def wheel_drag(self,event):
        if self._drag_grid is None:return
        cx,cy,radius=self.wheel_geometry();r,c=self.state.selected
        h=math.degrees(math.atan2(cy-event.y,event.x-cx))%360
        s=min(1,math.hypot(event.x-cx,event.y-cy)/radius)
        delta=(h-HUES[r]+180)%360-180
        try:
            self._drag_preview=edit_neighborhood(self._drag_grid,r,c,delta,s-SATS[c],self.state.radius,self.state.smoothness)
        except ValueError as exc:
            self.error.set(str(exc));return
        self.on_change(self._drag_preview,False);self.draw_wheel()

    def wheel_release(self,event=None):
        if self._drag_grid is None:return
        grid=self._drag_preview
        self._drag_grid=self._drag_preview=None
        if grid is not None:self.on_change(grid,True)
        self.show_node();self.redraw()

    def draw_table(self,component):
        canvas=self.tables[component];canvas.delete('all');cw,ch=self.cw,self.ch
        values=getattr(self.state.grid,component);r0,c0,r1,c1=self.bounds()
        for c,s in enumerate(SATS):canvas.create_text((c+1.5)*cw,ch/2,text=f'{s:g}')
        for r,h in enumerate(HUES):
            canvas.create_text(cw/2,(r+1.5)*ch,text=f'{h:g}°')
            for c,s in enumerate(SATS):
                x,y=(c+1)*cw,(r+1)*ch
                fill=self.color(h,s,self.state.value)
                active=r0<=r<=r1 and c0<=c<=c1
                canvas.create_rectangle(x,y,x+cw,y+ch,fill=fill,outline=COLORS['accent'] if active else '#aaa',width=3 if active else 1)
                rgb=colorsys.hsv_to_rgb(h/360,s,self.state.value)
                fg='#17212b' if sum(a*b for a,b in zip(rgb,(.2126,.7152,.0722)))>.52 else 'white'
                canvas.create_text(x+cw/2,y+ch/2,text=format_number(values[r*9+c],1 if component=='dh' else 3),fill=fg)
        canvas.configure(scrollregion=(0,0,cw*10,ch*25))
        r,c=self.state.selected;x,y=(c+1)*cw,(r+1)*ch
        canvas.create_rectangle(x+2,y+2,x+cw-2,y+ch-2,outline='white',width=5,tags='selected-node')
        canvas.create_rectangle(x+2,y+2,x+cw-2,y+ch-2,outline=COLORS['accent'],width=3,tags='selected-node')

    def table_press(self,event,component):
        if not self.finish_current_input():return 'break'
        canvas=self.tables[component];canvas.focus_set()
        r=int(canvas.canvasy(event.y)//self.ch)-1;c=int(canvas.canvasx(event.x)//self.cw)-1
        if 0<=r<24 and 0<=c<9:self.select_node(r,c,bool(event.state&1))
        return 'break'

    def table_key(self,event,component):
        r,c=self.state.selection_end
        steps={'Left':(0,-1),'Right':(0,1),'Up':(-1,0),'Down':(1,0)}
        if event.keysym in steps:
            if not self.finish_current_input():return 'break'
            dr,dc=steps[event.keysym];self.select_node(r+dr,c+dc,bool(event.state&1))
            self.tables[component].yview_moveto(max(0,(self.state.selection_end[0]-3)/25))
            self.tables[component].xview_moveto(max(0,(self.state.selection_end[1]-2)/10))
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
        index=max(0,min(191,r*8+max(0,c-1)+direction))
        self.select_node(index//8,index%8+1);self.open_inline(component)
        return 'break'

    def close_inline(self):
        if self.inline is not None:
            widget,self.inline=self.inline,None
            widget.unbind('<FocusOut>');widget.destroy()

    def copy_cells(self,component):
        r,c,rr,cc=self.bounds();values=getattr(self.state.grid,component)
        text='\n'.join('\t'.join(f'{values[row*9+col]:g}' for col in range(c,cc+1)) for row in range(r,rr+1))
        self.clipboard_clear();self.clipboard_append(text);return 'break'

    def paste_cells(self,component,text=None):
        try:
            if self.state.drafts:raise ValueError('请先提交或重置未完成的数字输入')
            text=self.clipboard_get() if text is None else text
            rows=[[float(v) for v in row.split()] for row in text.strip().splitlines()]
            if not rows or not rows[0] or any(len(row)!=len(rows[0]) for row in rows):raise ValueError('需要矩形 TSV 数字区域')
            r,c,_,_=self.bounds();grid=self.state.grid.patch(component,r,c,rows)
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
