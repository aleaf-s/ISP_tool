"""Resizable CA Y→UV gain curve editor. All edits stay in the draft curve."""
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

from ...grading.ca import CACurve
from ..theme import COLORS
from .tooltip import Tooltip


class CAEditor(ttk.Frame):
    def __init__(self, parent, on_change, on_apply, on_restore, on_load, on_save, error, on_pending=None):
        super().__init__(parent, padding=10)
        self.on_change = on_change
        self.error = error
        self.on_pending = on_pending or (lambda: None)
        self.state = None
        self._rendering = False
        self._dragging = False
        self._drag_curve = None
        self._preview = None
        self.x_var = tk.StringVar(self, '128')
        self.y_var = tk.StringVar(self, '1024')
        self.status = tk.StringVar(self, '已应用')
        self.count = tk.StringVar(self)
        self._focus_job = None
        self._query_y = None
        footer = ttk.Frame(self)
        footer.pack(side='bottom', fill='x', pady=(8, 0))
        self.apply_button = ttk.Button(footer, text='应用', command=on_apply, style='Primary.TButton')
        self.apply_button.pack(side='right')
        ttk.Button(footer, text='恢复到上次应用', command=on_restore).pack(side='right', padx=6)
        ttk.Label(footer, textvariable=self.status, style='Muted.TLabel').pack(side='left')
        # Reserve the controls BEFORE expanding the plot; never use a fixed
        # pixel width for a DPI-scaled stack of widgets.
        side_host = ttk.Frame(self)
        side_host.pack(side='right', fill='y')
        self.side_canvas = tk.Canvas(side_host, highlightthickness=0, bg=COLORS['panel'])
        scrollbar = ttk.Scrollbar(side_host, orient='vertical', command=self.side_canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.side_canvas.pack(side='left', fill='both', expand=True)
        self.side_canvas.configure(yscrollcommand=scrollbar.set)
        side = ttk.Frame(self.side_canvas, padding=(6, 0, 6, 6))
        self.side = side
        self._side_window = self.side_canvas.create_window(0, 0, window=side, anchor='nw')
        side.bind('<Configure>', lambda e: self.side_canvas.configure(
            scrollregion=self.side_canvas.bbox('all'), width=side.winfo_reqwidth()))
        self.side_canvas.bind('<Configure>', lambda e: self.side_canvas.itemconfigure(self._side_window, width=e.width))
        plot = ttk.Frame(self)
        plot.pack(side='left', fill='both', expand=True, padx=(0, 12))
        ttk.Label(plot, text='Chroma Adjust', style='Title.TLabel').pack(anchor='w')
        note=ttk.Label(plot, text='1024 = 1×', style='Muted.TLabel');note.pack(anchor='w')
        Tooltip(note, '软件近似：使用 BT.709 亮度选择 UV 增益，设备 ISO 增益和量化尚待确认。')
        self.canvas = tk.Canvas(plot, bg=COLORS['panel'], highlightthickness=1,
                                highlightbackground=COLORS['border'], width=700, height=520)
        self.canvas.pack(fill='both', expand=True, pady=(6, 0))
        self.canvas.bind('<Configure>', lambda e: self.redraw())
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Double-Button-1>', self.double_click)
        self.canvas.bind('<Button-3>', self.right_click)
        self.canvas.bind('<Delete>', lambda e: self.delete_point())
        ttk.Label(side, text='CA 曲线', style='Title.TLabel').pack(anchor='w')
        ttk.Button(side, text='导入 CA TXT…', command=on_load).pack(fill='x', pady=(8, 4))
        ttk.Button(side, text='导出 CA TXT（256 点）…', command=on_save).pack(fill='x')
        ttk.Separator(side).pack(fill='x', pady=14)
        self.entries = []
        for title, variable in (('X · 亮度 Y（0～255）', self.x_var), ('Y · 色度增益（0～2047）', self.y_var)):
            ttk.Label(side, text=title).pack(anchor='w', pady=(4, 2))
            entry = ttk.Entry(side, textvariable=variable, width=12, justify='right')
            entry.pack(anchor='w')
            if variable is self.x_var:
                entry.bind('<Return>', lambda e: self.query_x())
                entry.bind('<FocusOut>', self.x_focus_out)
            else:
                entry.bind('<Return>', lambda e: self.set_point())
                entry.bind('<FocusOut>', self.focus_out)
            self.entries.append(entry)
        ttk.Button(side, text='设置结点', command=self.set_point).pack(fill='x', pady=(12, 4))
        self.add_button = ttk.Button(side, text='添加控制点', command=self.add_point)
        self.add_button.pack(fill='x', pady=4)
        self.delete_button = ttk.Button(side, text='删除选中控制点', command=self.delete_point)
        self.delete_button.pack(fill='x', pady=4)
        Tooltip(self.delete_button, '右键节点或选中后按 Delete 也可删除；X=0、255 端点保留。')
        ttk.Label(side, textvariable=self.count, style='Muted.TLabel').pack(anchor='w', pady=4)
        ttk.Label(side, text='双击曲线区域添加 · 拖动节点调整', style='Muted.TLabel').pack(anchor='w')
        ttk.Separator(side).pack(fill='x', pady=12)
        row = ttk.Frame(side); row.pack(fill='x')
        self.undo_button = ttk.Button(row, text='撤销', command=lambda: self.travel(False))
        self.undo_button.pack(side='left')
        self.redo_button = ttk.Button(row, text='重做', command=lambda: self.travel(True))
        self.redo_button.pack(side='left', padx=6)
        ttk.Button(side, text='重置为 1×', command=self.reset).pack(fill='x', pady=(10, 4))
        ttk.Label(side, textvariable=error, style='Error.TLabel', wraplength=240).pack(fill='x', pady=10)
        def bind_scroll(widget):
            widget.bind('<MouseWheel>', self.scroll_side, add='+')
            for child in widget.winfo_children(): bind_scroll(child)
        bind_scroll(side_host)
        self._traces=[(variable,variable.trace_add('write',self.remember_draft))
                      for variable in (self.x_var,self.y_var)]

    def scroll_side(self, event):
        if self.side.winfo_height() > self.side_canvas.winfo_height():
            self.side_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def focus_out(self, event=None):
        if self._focus_job: self.after_cancel(self._focus_job)
        state = self.state
        def commit():
            self._focus_job = None
            if self.state is not state or state is None or not self.winfo_ismapped(): return
            if self.focus_get() in self.entries: return
            if state.drafts is not None:
                # A new X is an addition draft; leave it for Add/Apply, not a
                # silent move of the previously selected point.
                try:
                    x, _ = self._numbers()
                    if x not in dict(state.curve.points):
                        self.status.set('新节点待添加'); return
                except ValueError as exc:
                    self.error.set(str(exc)); return
                self.commit_draft()
        self._focus_job = self.after_idle(commit)

    def query_x(self):
        """PQTools-style X lookup. Never overwrite an explicitly edited Y."""
        if self.state is None: return False
        try:
            x=int(self.x_var.get())
            if not 0<=x<=255:raise ValueError()
        except ValueError:
            self.error.set('X 需要输入 0～255 的整数');return False
        if self.y_var.get() not in (str(self.state.curve.values[self.state.selected_x]),self._query_y):return True
        if x in dict(self.state.curve.points):
            self.state.selected_x=x;self.show_selection()
        else:
            self.y_var.set(str(self.state.curve.values[x]))
            self._query_y=self.y_var.get()
            self.status.set('新节点待添加')
        self.error.set('');return True

    def x_focus_out(self, event=None):
        if self.winfo_ismapped() and self.query_x():self.focus_out(event)

    def right_click(self, event):
        if self.state is None:return 'break'
        if self.state.drafts is not None and not self.commit_draft():return 'break'
        distance,x=min((abs(event.x-self.point_xy(x,y)[0])+abs(event.y-self.point_xy(x,y)[1]),x)
                       for x,y in self.state.curve.points)
        if distance<=22:
            self.state.selected_x=x;self.delete_point()
        return 'break'

    def double_click(self, event):
        if self.state is None: return 'break'
        self._dragging = False; self._preview = self._drag_curve = None
        left, top, right, bottom = self.bounds()
        if not left <= event.x <= right or not top <= event.y <= bottom: return 'break'
        if self.state.drafts is not None and not self.commit_draft(): return 'break'
        x = max(0, min(255, round((event.x-left)*255/(right-left))))
        if x in dict(self.state.curve.points):
            self.state.selected_x=x;self.show_selection()
            self.error.set('该 X 已有控制点，已选中；请拖动或修改 Y')
            return 'break'
        self.x_var.set(str(x)); self.y_var.set(str(self.from_y(event.y)))
        self.add_point()
        self.canvas.focus_set()
        return 'break'

    def remember_draft(self, *_):
        if self._rendering or self.state is None:return
        text=(self.x_var.get(),self.y_var.get())
        canonical=(str(self.state.selected_x),str(self.state.curve.values[self.state.selected_x]))
        self.state.drafts=text if text!=canonical else None
        self.on_pending()

    def set_state(self, state):
        if self.state is not state:self.remember_draft()
        self.state = state
        self._dragging = False
        self._preview = None
        pending=state.drafts
        self.show_selection()
        if pending is not None:
            self._rendering=True
            self.x_var.set(pending[0]);self.y_var.set(pending[1])
            self._rendering=False
            state.drafts=pending
            self.on_pending()

    def show_selection(self):
        if self.state is None: return
        self._query_y=None
        self.state.drafts=None
        self._rendering = True
        if self.state.selected_x not in dict(self.state.curve.points):
            self.state.selected_x = min(self.state.curve.points, key=lambda p: abs(p[0]-self.state.selected_x))[0]
        x = self.state.selected_x
        self.x_var.set(str(x))
        self.y_var.set(str(self.state.curve.values[x]))
        self.status.set('待应用' if self.state.curve != self.state.applied else '已应用')
        self._rendering = False
        self.count.set(f'控制点 {len(self.state.curve.points)} / 64 · 导出 256 点')
        self.delete_button.configure(state='disabled' if x in (0,255) else 'normal')
        self.add_button.configure(state='disabled' if len(self.state.curve.points)>=64 else 'normal')
        self.undo_button.configure(state='normal' if self.state.undo_stack else 'disabled')
        self.redo_button.configure(state='normal' if self.state.redo_stack else 'disabled')
        self.redraw()
        self.on_pending()

    def bounds(self):
        width, height = max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
        font = tkfont.nametofont('TkDefaultFont')
        left = font.measure('2047')+14
        pad = font.metrics('linespace')
        return left, pad, max(left+10,width-pad), max(pad+10,height-pad*2)

    def point_xy(self, x, y):
        left, top, right, bottom = self.bounds()
        return left+(right-left)*x/255, bottom-(bottom-top)*y/2047

    def from_y(self, pixel_y):
        _, top, _, bottom = self.bounds()
        return max(0, min(2047, round((bottom-pixel_y)*2047/(bottom-top))))

    def redraw(self):
        self.canvas.delete('all')
        if self.state is None: return
        left, top, right, bottom = self.bounds()
        for x in (0, 64, 128, 191, 255):
            px, _ = self.point_xy(x, 0)
            self.canvas.create_line(px, top, px, bottom, fill='#d2d9e0', dash=(3, 3))
            self.canvas.create_text(px, bottom+15, text=str(x), fill=COLORS['muted'])
        for y in (0, 512, 1024, 1535, 2047):
            _, py = self.point_xy(0, y)
            self.canvas.create_line(left, py, right, py, fill='#d2d9e0', dash=(3, 3))
            self.canvas.create_text(left-7, py, text=str(y), anchor='e', fill=COLORS['muted'])
        self.canvas.create_line(left, top, left, bottom, right, bottom, fill=COLORS['foreground'])
        curve = self._preview or self.state.curve
        path = [coordinate for x, y in enumerate(curve.values) for coordinate in self.point_xy(x, y)]
        self.canvas.create_line(*path, fill='#e33a34', width=2)
        for x, y in curve.points:
            px, py = self.point_xy(x, y)
            selected = x == self.state.selected_x
            r = 6 if selected else 4
            self.canvas.create_oval(px-r, py-r, px+r, py+r, fill='#e33a34',
                                    outline='white' if selected else '#a72220', width=2 if selected else 1)

    def press(self, event):
        if self.state is None: return
        self.canvas.focus_set()
        if self.state.drafts is not None and not self.commit_draft():return
        candidates = [(abs(event.x-self.point_xy(x,y)[0])+abs(event.y-self.point_xy(x,y)[1]),x)
                      for x,y in self.state.curve.points]
        distance, x = min(candidates)
        if distance > 22: return
        self.state.selected_x = x
        self._dragging = True
        self._drag_curve = self.state.curve
        self.show_selection()

    def drag(self, event):
        if not self._dragging: return
        try:
            self._preview = self._drag_curve.set_point(self.state.selected_x, self.from_y(event.y))
            self.redraw()
        except ValueError as exc:
            self.error.set(str(exc))

    def release(self, event=None):
        if not self._dragging: return
        self._dragging = False
        preview, self._preview = self._preview, None
        self._drag_curve = None
        if preview is not None: self.on_change(preview)
        self.show_selection()

    def _numbers(self):
        try:
            x, y = int(self.x_var.get()), int(self.y_var.get())
        except ValueError as exc:
            raise ValueError('X 和 Y 需要输入整数') from exc
        if not 0 <= x <= 255 or not 0 <= y <= 2047:
            raise ValueError('X 范围 0～255；Y 范围 0～2047')
        return x, y

    def commit_draft(self):
        """Apply/Save accepts unsubmitted valid text, but never silently drops it."""
        if self.state is None or self._dragging: return False
        if (self.x_var.get(), self.y_var.get()) == (str(self.state.selected_x), str(self.state.curve.values[self.state.selected_x])):
            return True
        return self.set_point()

    def set_point(self):
        try:
            x, y = self._numbers()
            if x not in dict(self.state.curve.points):
                raise ValueError('该 X 尚无控制点，请点击“添加控制点”')
            self.on_change(self.state.curve.set_point(x, y))
            self.state.selected_x = x
            self.error.set(''); self.show_selection()
            return True
        except ValueError as exc:
            self.error.set(str(exc)); return False

    def add_point(self):
        try:
            x, y = self._numbers()
            if x in dict(self.state.curve.points): raise ValueError('该 X 已有控制点，请使用“设置结点”')
            self.on_change(self.state.curve.set_point(x, y))
            self.state.selected_x = x
            self.error.set(''); self.show_selection()
            return True
        except ValueError as exc: self.error.set(str(exc)); return False

    def delete_point(self):
        try:
            curve = self.state.curve.remove_point(self.state.selected_x)
            self.on_change(curve)
            self.state.selected_x = min(curve.points, key=lambda p: abs(p[0]-self.state.selected_x))[0]
            self.error.set(''); self.show_selection()
        except ValueError as exc: self.error.set(str(exc))

    def reset(self):
        self.on_change(CACurve())
        self.error.set(''); self.show_selection()

    def travel(self, redo):
        if self.state and self.state.travel(redo):
            self.error.set(''); self.show_selection();self.on_pending()

    def destroy(self):
        if self._focus_job: self.after_cancel(self._focus_job)
        super().destroy()
