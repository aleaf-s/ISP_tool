"""Transactional, compact editor for a device-specific AWB/CCM table."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from ..awb_ccm_table import CalibrationPoint, CalibrationTable, matrix_tuple
from .widgets.ccm_matrix_editor import CCMMatrixEditor, FIXED


class AWBCCMTableDialog(tk.Toplevel):
    def __init__(self,parent,table,on_apply):
        super().__init__(parent)
        self.title('AWB 仿真 · 标定表')
        self.transient(parent.winfo_toplevel())
        self.points=list(table.points);self.selected=-1;self.on_apply=on_apply
        self.name=tk.StringVar(self,value=table.name)
        self.error=tk.StringVar(self)
        self._loaded_point=None;self._original=table
        body=ttk.Frame(self,padding=12);body.pack(fill='both',expand=True)
        row=ttk.Frame(body);row.pack(fill='x')
        ttk.Label(row,text='设备 / 配置名称').pack(side='left')
        ttk.Entry(row,textvariable=self.name,width=28).pack(side='left',padx=8,fill='x',expand=True)
        listing=ttk.Frame(body);listing.pack(fill='both',expand=True,pady=8)
        self.tree=ttk.Treeview(listing,columns=('cct','r','b'),show='headings',height=6,selectmode='browse')
        for key,label in (('cct','色温 K'),('r','R/G ×1024'),('b','B/G ×1024')):
            self.tree.heading(key,text=label);self.tree.column(key,width=130,anchor='center')
        self.tree.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(listing,command=self.tree.yview);scroll.pack(side='right',fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>',self.select)
        form=ttk.Frame(body);form.pack(fill='x')
        self.fields=[]
        for column,label in enumerate(('色温 K','R/G','B/G')):
            ttk.Label(form,text=label).grid(row=0,column=column,sticky='w')
            var=tk.StringVar(self);self.fields.append(var)
            ttk.Entry(form,textvariable=var,width=10).grid(row=1,column=column,padx=(0,8),pady=4)
        self.matrix=CCMMatrixEditor(body,np.eye(3),tk.StringVar(self,value=FIXED))
        self.matrix.pack(fill='x',pady=6)
        actions=ttk.Frame(body);actions.pack(fill='x')
        for label,command in (('更新选中',self.update_point),('添加为新点',self.add_point),('删除选中',self.delete_point)):
            ttk.Button(actions,text=label,command=command).pack(side='left',padx=(0,5))
        ttk.Label(body,textvariable=self.error,style='Error.TLabel',wraplength=480).pack(fill='x',pady=6)
        files=ttk.Frame(body);files.pack(fill='x')
        for label,command in (('加载 JSON',self.load),('保存 JSON',self.save),('恢复默认表',self.reset)):
            ttk.Button(files,text=label,command=command).pack(side='left',padx=(0,5))
        ttk.Button(body,text='保存并使用',command=self.accept,style='Primary.TButton').pack(fill='x',pady=(10,0))
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh(0)

    def point_draft(self):
        texts=[v.get().strip() for v in self.fields]
        if any(not t.isascii() or not t.isdecimal() for t in texts):raise ValueError('色温和 Gain 必须是正整数')
        return CalibrationPoint(*(int(t) for t in texts),matrix_tuple(self.matrix.matrix()))

    def has_draft(self):
        message=self.matrix.message_var.get()
        try:return self.point_draft()!=self._loaded_point
        except (ValueError,np.linalg.LinAlgError):return True
        finally:self.matrix.message_var.set(message)

    def allow_discard(self):
        return not self.has_draft() or messagebox.askyesno('未更新的标定点','放弃当前输入草稿？',parent=self)

    def refresh(self,index):
        self.tree.delete(*self.tree.get_children())
        for i,p in enumerate(self.points):self.tree.insert('', 'end',iid=str(i),values=(p.cct,p.r_gain,p.b_gain))
        self.selected=min(max(index,0),len(self.points)-1)
        if self.selected>=0:
            self.tree.selection_set(str(self.selected));self.tree.see(str(self.selected));self.show_point()

    def show_point(self):
        p=self.points[self.selected]
        for v,value in zip(self.fields,(p.cct,p.r_gain,p.b_gain)):v.set(str(value))
        self.matrix.set_matrix(p.ccm);self._loaded_point=p;self.error.set('')

    def select(self,event=None):
        selected=self.tree.selection()
        if not selected:return
        index=int(selected[0])
        if index==self.selected:return
        if not self.allow_discard():
            self.tree.selection_set(str(self.selected));return
        self.selected=index;self.show_point()

    def validated(self,points=None):
        return CalibrationTable(tuple(self.points if points is None else points),self.name.get().strip())

    def update_point(self):
        try:
            p=self.point_draft();points=list(self.points);points[self.selected]=p
            table=self.validated(points);self.points=list(table.points);self.refresh(self.points.index(p))
        except (ValueError,np.linalg.LinAlgError) as exc:self.error.set(str(exc))

    def add_point(self):
        try:
            p=self.point_draft();table=self.validated(self.points+[p])
            self.points=list(table.points);self.refresh(self.points.index(p))
        except (ValueError,np.linalg.LinAlgError) as exc:self.error.set(str(exc))

    def delete_point(self):
        try:
            if not self.allow_discard():return
            points=list(self.points);points.pop(self.selected)
            table=self.validated(points);self.points=list(table.points);self.refresh(self.selected)
        except ValueError as exc:self.error.set(str(exc))

    def _table_for_action(self):
        if self.has_draft():raise ValueError('请先“更新选中”或“添加为新点”，再使用或保存标定表')
        return self.validated()

    def accept(self):
        try:self.on_apply(self._table_for_action())
        except (OSError,ValueError,np.linalg.LinAlgError) as exc:self.error.set(str(exc));return
        self.destroy()

    def save(self):
        try:table=self._table_for_action()
        except ValueError as exc:self.error.set(str(exc));return
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.json',filetypes=[('标定表 JSON','*.json')])
        if not path:return
        try:
            # Float avoids quantizing edited/interpolated coefficients on save.
            Path(path).write_text(json.dumps(table.to_payload(),ensure_ascii=False,indent=2),encoding='utf-8')
            self.error.set('已保存；CCM 使用实际 Float 系数，Gain 使用 ×1024 整数')
        except OSError as exc:self.error.set(str(exc))

    def load(self):
        if not self.allow_discard():return
        path=filedialog.askopenfilename(parent=self,filetypes=[('标定表 JSON','*.json')])
        if not path:return
        try:
            if Path(path).stat().st_size>1024*1024:raise ValueError('标定 JSON 超过 1 MiB')
            table=CalibrationTable.from_payload(json.loads(Path(path).read_text(encoding='utf-8-sig')))
            self.points=list(table.points);self.name.set(table.name);self.refresh(0)
        except (ValueError,TypeError,OSError,np.linalg.LinAlgError) as exc:self.error.set(str(exc))

    def reset(self):
        if not messagebox.askyesno('恢复默认表','用提供的五组默认标定替换窗口中的草稿？不改变原 CCM 或已应用图像。',parent=self):return
        table=CalibrationTable.default();self.points=list(table.points);self.name.set(table.name);self.refresh(0)

    def close(self):
        changed=self.has_draft() or self.name.get()!=self._original.name or tuple(self.points)!=self._original.points
        if changed and not messagebox.askyesno('未使用的标定表','关闭并放弃窗口内修改？',parent=self):return
        self.destroy()
