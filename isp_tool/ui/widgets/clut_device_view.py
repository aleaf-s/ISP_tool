"""Read-only device words and decoded nodes, never reconstructed HSV values."""
import tkinter as tk
from tkinter import ttk
import numpy as np
from pathlib import Path
from .tooltip import Tooltip
from ...grading.hisi_clut import addresses, unpack_words


class CLUTDeviceView(ttk.Frame):
    PAGE_SIZE = 128

    def __init__(self, parent):
        super().__init__(parent)
        self.words=();self.delta=None;self._addresses=None;self._rendered_key=None
        self.summary=tk.StringVar(self,value='尚未导入设备 CLUT；此页不显示 HSV 调色参数')
        label=ttk.Label(self,textvariable=self.summary,wraplength=700);label.pack(anchor='w',pady=5)
        self.path='';Tooltip(label,lambda:self.path or '原始整数及按当前适配器解码的 RGB 差值；索引从 0 开始')
        self.bind('<Configure>',lambda e:label.configure(wraplength=max(200,e.width-12)))
        bar=ttk.Frame(self);bar.pack(fill='x')
        self.mode=tk.StringVar(self,value='RGB 节点')
        box=ttk.Combobox(bar,textvariable=self.mode,values=('RGB 节点','原始整数'),state='readonly',width=12)
        box.pack(side='left');box.bind('<<ComboboxSelected>>',self.change_mode)
        self.index=tk.StringVar(self,value='0');self.index_label=ttk.Label(bar,text='B 层');self.index_label.pack(side='left',padx=5)
        self.selector=ttk.Combobox(bar,textvariable=self.index,values=tuple(range(17)),state='readonly',width=5)
        self.selector.pack(side='left');self.selector.bind('<<ComboboxSelected>>',lambda e:self.render())
        ttk.Label(bar,text='只读 · Ctrl+C 复制').pack(side='left',padx=8)
        body=ttk.Frame(self);body.pack(fill='both',expand=True,pady=5)
        columns=('address','r','g','b','dr','dg','db','word')
        self.table=ttk.Treeview(body,columns=columns,show='headings',height=10)
        for key,title in zip(columns,('文件索引','R 索引','G 索引','B 索引','ΔR','ΔG','ΔB','原始整数')):
            self.table.heading(key,text=title);self.table.column(key,width=120 if key=='word' else 75,minwidth=50,anchor='e')
        ys=ttk.Scrollbar(body,orient='vertical',command=self.table.yview)
        xs=ttk.Scrollbar(body,orient='horizontal',command=self.table.xview)
        self.table.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
        self.table.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns');xs.grid(row=1,column=0,sticky='ew')
        body.rowconfigure(0,weight=1);body.columnconfigure(0,weight=1)
        self.table.bind('<Control-c>',self.copy)

    def set_grid(self, grid, path=''):
        self.path=path
        words=grid.base_words if grid is not None else ()
        changed=words!=self.words
        self.words=words
        if not words:
            self.delta=None;self.summary.set('尚未导入设备 CLUT；此页不显示 HSV 调色参数')
        else:
            if changed:
                self.delta=unpack_words(words)
                coords,positions=addresses()
                self._addresses=np.zeros((17,17,17),int)
                self._addresses[coords[:,0],coords[:,1],coords[:,2]]=positions
                self._by_address={int(pos):tuple(map(int,c)) for c,pos in zip(coords,positions)}
                active=np.argwhere(np.any(self.delta!=0,axis=-1))
                if len(active):
                    r,g,b=active[0]
                    self.index.set(str(int(b) if self.mode.get()=='RGB 节点' else int(self._addresses[r,g,b])//self.PAGE_SIZE))
            nonzero=int(np.count_nonzero(words))
            self.summary.set(f'{Path(path).name if path else "设备 CLUT"} · 5508 个整数 / 4913 个节点 · 非零 {nonzero}')
        self.render()

    def change_mode(self,event=None):
        raw=self.mode.get()=='原始整数'
        self.index_label.configure(text='页' if raw else 'B 层')
        self.selector.configure(values=tuple(range(44 if raw else 17)))
        self.index.set('0');self.render()

    def render(self):
        key=(self.words,self.mode.get(),self.index.get())
        if key==self._rendered_key:return
        self._rendered_key=key
        self.table.delete(*self.table.get_children())
        if not self.words:return
        index=int(self.index.get())
        if self.mode.get()=='原始整数':
            positions=range(index*self.PAGE_SIZE,min(5508,(index+1)*self.PAGE_SIZE))
        else:
            positions=[int(self._addresses[r,g,index]) for g in range(17) for r in range(17)]
        selected=None
        for pos in positions:
            coords=self._by_address.get(pos)
            if coords is None:values=(pos,'填充','—','—','—','—','—',self.words[pos])
            else:values=(pos,*coords,*map(int,self.delta[coords]),self.words[pos])
            item=self.table.insert('', 'end', values=values)
            if selected is None and self.words[pos]!=0:selected=item
        if selected is not None:
            self.table.selection_set(selected);self.table.see(selected)

    def copy(self,event=None):
        rows=['\t'.join(map(str,self.table.item(i,'values'))) for i in self.table.selection()]
        if rows:self.clipboard_clear();self.clipboard_append('\n'.join(rows))
        return 'break'
