"""Explicit-apply, single screenshot AWB workspace; no RAW pipeline mutation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog
import cv2
import numpy as np
from PIL import Image
from ..awb_retune import RetuneSettings, retune_screenshot, MAX_GAIN
from ..awb_ccm_table import CalibrationTable, matrix_tuple
from ..awb_calibration_store import CalibrationStore
from ..grading.image_io import read_color_image, export_processed_image
from ..grading.model import raster8
from .theme import COLORS
from .widgets.ccm_matrix_editor import CCMMatrixEditor, FIXED
from .widgets.comparison_view import ComparisonViewMixin
from .widgets.tool_selector import ToolSelector
from .widgets.tooltip import Tooltip


SAME = '与原 CCM 相同'
AUTO = '按目标 Gain 自动联动'
MANUAL = '手动输入'


class AWBRetuneWorkspace(ComparisonViewMixin, ttk.Frame):
    def __init__(self,parent,tool_variable,on_tool,calibration_path=None):
        super().__init__(parent)
        self.document=None
        self.calibration_store=CalibrationStore(calibration_path)
        load_warning=''
        try:self.table=self.calibration_store.load()
        except (OSError,ValueError,TypeError,np.linalg.LinAlgError) as exc:
            self.table=CalibrationTable.default()
            load_warning=f'标定表读取失败，暂用默认表；原文件未覆盖：{exc}'
        self.table_dialog=None
        self.last_lookup=None
        self._updating_link=False
        self._manual_snapshot=None
        self._previous_source=AUTO
        self._estimated_original=None
        self._original_estimate_warning=''
        self.source=self.output=self.source_pil=self.output_pil=None
        self.zoom=1.;self.offset=[0.,0.];self.fit=True;self.divider=.5
        self.drag=None;self.hold_original=False;self._photos=[]
        self.revision=0;self._shown_revision=-1
        self._render_timer=None;self._dirty_timer=None;self._timers=set()
        self.closed=False;self.future=None;self.io_future=None
        self.executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='awb-retune')
        self.applied_settings=RetuneSettings()
        self.requested_settings=self.applied_settings
        self.empty_text='导入截图，填写 AWB Gain 和 CCM，然后点击“应用”'
        self.status=tk.StringVar(self,value='PNG / JPG 截图 · 近似预览')
        self.error=tk.StringVar(self)
        self.dirty_label=tk.StringVar(self)
        self.storage_warning=tk.StringVar(self,value=load_warning)
        self._status_traces=[]
        self.filename=tk.StringVar(self,value='未导入图像')
        self.enabled=tk.BooleanVar(self,value=True)
        self.mode=tk.StringVar(self,value='滑动对比')
        bar=ttk.Frame(self,padding=8);bar.pack(fill='x')
        self.tool_selector=ToolSelector(bar,tool_variable,on_tool)
        self.tool_selector.pack(side='left',padx=(0,8))
        ttk.Button(bar,text='导入截图',command=self.open_images,style='Primary.TButton').pack(side='left')
        ttk.Label(bar,textvariable=self.filename,width=24).pack(side='left',padx=8)
        Tooltip(bar,lambda:self.document.path if self.document else '')
        ttk.Button(bar,text='导出结果',command=self.export).pack(side='right')
        body=ttk.Frame(self,padding=(8,0,8,8));body.pack(fill='both',expand=True)
        right_host=ttk.Frame(body,padding=(12,0,0,0));right_host.pack(side='right',fill='y')
        self.action_footer=ttk.Frame(right_host,padding=(0,6,0,0))
        self.action_footer.pack(side='bottom',fill='x')
        self.compact_notice(self.action_footer,self.dirty_label)
        ttk.Button(self.action_footer,text='应用',command=self.apply,style='Primary.TButton').pack(fill='x',pady=4)
        self.compact_notice(self.action_footer,self.error,style='Error.TLabel')
        self.compact_notice(self.action_footer,self.storage_warning,style='Error.TLabel')
        parameter_area=ttk.Frame(right_host);parameter_area.pack(fill='both',expand=True)
        self.parameter_canvas=tk.Canvas(parameter_area,highlightthickness=0,bg=COLORS['panel'],width=310)
        scroll=ttk.Scrollbar(parameter_area,command=self.parameter_canvas.yview)
        scroll.pack(side='right',fill='y')
        self.parameter_canvas.configure(yscrollcommand=scroll.set)
        self.parameter_canvas.pack(side='left',fill='both',expand=True)
        right=ttk.Frame(self.parameter_canvas)
        window=self.parameter_canvas.create_window(0,0,window=right,anchor='nw')
        right.bind('<Configure>',lambda e:self.parameter_canvas.configure(width=right.winfo_reqwidth(),scrollregion=self.parameter_canvas.bbox('all')))
        self.parameter_canvas.bind('<Configure>',lambda e:self.parameter_canvas.itemconfigure(window,width=e.width))
        heading=ttk.Frame(right);heading.pack(fill='x',pady=(0,6))
        title=ttk.Label(heading,text='AWB 仿真',style='Title.TLabel');title.pack(side='left')
        Tooltip(title,'近似仿真：假定播放器已完成 BT.709 → sRGB 转换并保持相对线性亮度。曝光固定，Offset=0，不能恢复高光裁剪或播放器额外处理。')
        table_button=ttk.Button(heading,text='标定表…',command=self.open_table)
        table_button.pack(side='right')
        Tooltip(table_button,lambda:f'保存并使用后，下次自动恢复。\n{self.calibration_store.path}')
        self.gains={}
        self.format=tk.StringVar(self,value=FIXED)
        self.ccm_source=tk.StringVar(self,value=AUTO)
        self.link_info=tk.StringVar(self,value='')
        self.original_info=tk.StringVar(self)
        self.parameter_groups={}
        for group,label in (('current','原参数'),('target','目标参数')):
            section=ttk.LabelFrame(right,text=label,padding=8)
            section.pack(fill='x',pady=(0,8));self.parameter_groups[group]=section
            ttk.Label(section,text='AWB · ×1024').pack(anchor='w',pady=(0,4))
            row=ttk.Frame(section);row.pack(anchor='w')
            self.gains[group]=[]
            for channel in ('R/G','B/G'):
                ttk.Label(row,text=channel).pack(side='left',padx=(0,4))
                var=tk.StringVar(self,value='1024')
                entry=ttk.Entry(row,textvariable=var,width=7,justify='right',style='Parameter.TEntry')
                entry.pack(side='left',padx=(0,10))
                Tooltip(entry,lambda v=var:f'1024 = 1×；软件范围 1…{MAX_GAIN}；当前倍率 '+(f'{int(v.get())/1024:.4g}×' if v.get().isascii() and v.get().isdecimal() else '—'))
                self.gains[group].append(var)
            if group=='current':
                ccm_label=ttk.Label(section,text='CCM');ccm_label.pack(anchor='w',pady=(8,4))
                Tooltip(ccm_label,'生成原图时使用的 CCM；RGB 列向量左乘。')
                self.matrix_editor=CCMMatrixEditor(section,np.eye(3),self.format,compact=True)
                self.matrix_editor.pack(fill='x')
                ttk.Button(section,text='按原 Gain 估算 CCM',command=self.estimate_original).pack(anchor='w',pady=(4,0))
                self.compact_notice(section,self.original_info)
        target_group=self.parameter_groups['target']
        ttk.Label(target_group,text='CCM').pack(anchor='w',pady=(8,4))
        self.source_combo=ttk.Combobox(target_group,textvariable=self.ccm_source,values=(SAME,AUTO,MANUAL),state='readonly',width=24)
        self.source_combo.pack(fill='x',pady=4)
        self.target_editor=CCMMatrixEditor(target_group,np.eye(3),self.format,compact=True)
        self.target_editor.pack(fill='x')
        self.target_editor.set_readonly()
        self.link_label=self.compact_notice(target_group,self.link_info)
        Tooltip(self.link_label,lambda: self.lookup_details())
        ttk.Button(target_group,text='恢复为原参数',command=self.reset_target).pack(anchor='w',pady=(6,0))
        left=ttk.Frame(body);left.pack(side='left',fill='both',expand=True)
        toolbar=ttk.Frame(left);toolbar.pack(fill='x',pady=(0,6))
        combo=ttk.Combobox(toolbar,textvariable=self.mode,values=('左右并排','滑动对比'),state='readonly',width=10)
        combo.pack(side='left')
        combo.bind('<<ComboboxSelected>>',lambda e:self.fit_image())
        ttk.Button(toolbar,text='适应窗口',command=self.fit_image).pack(side='left',padx=6)
        original=ttk.Button(toolbar,text='按住看原图');original.pack(side='left')
        original.bind('<ButtonPress-1>',lambda e:self.show_original(True))
        original.bind('<ButtonRelease-1>',lambda e:self.show_original(False))
        original.bind('<Leave>',lambda e:self.show_original(False))
        self.canvas=tk.Canvas(left,bg='#707070',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        for event,command in (('<Configure>',lambda e:self.schedule_draw()),('<ButtonPress-1>',self.press),('<B1-Motion>',self.motion),('<ButtonRelease-1>',lambda e:setattr(self,'drag',None)),('<MouseWheel>',self.wheel),('<Motion>',self.hover)):
            self.canvas.bind(event,command)
        ttk.Label(self,textvariable=self.status,style='Muted.TLabel',padding=8).pack(fill='x')
        self._traces=[]
        for var in self.gains['current']+self.gains['target']+self.matrix_editor.variables+self.target_editor.variables+[self.ccm_source]:
            self._traces.append((var,var.trace_add('write',self.queue_dirty)))
        def scroll_parameters(event):
            bounds=self.parameter_canvas.bbox('all')
            if bounds and bounds[3]>self.parameter_canvas.winfo_height():
                self.parameter_canvas.yview_scroll(-3 if event.delta>0 else 3,'units')
            return 'break'
        def bind_scroll(widget):
            widget.bind('<MouseWheel>',scroll_parameters)
            for child in widget.winfo_children():bind_scroll(child)
        bind_scroll(right)
        self.parameter_canvas.bind('<MouseWheel>',scroll_parameters)
        self.refresh_dirty()

    def compact_notice(self,parent,variable,style='Muted.TLabel'):
        # Keep pack order stable while allowing empty notices to take no space.
        slot=ttk.Frame(parent);slot.pack(fill='x')
        label=ttk.Label(slot,textvariable=variable,style=style,wraplength=300)
        def update(*_):
            if variable.get():
                slot.pack_propagate(True)
                label.pack(fill='x',pady=(4,0))
            else:
                label.pack_forget()
                slot.pack_propagate(False)
                slot.configure(height=1)
        self._status_traces.append((variable,variable.trace_add('write',update)))
        update()
        return label

    def later(self,ms,callback):
        def run():
            self._timers.discard(identifier)
            if not self.closed:callback()
        identifier=self.after(ms,run);self._timers.add(identifier)
        return identifier

    def queue_dirty(self,*_):
        if not self._updating_link and self._dirty_timer is None:self._dirty_timer=self.later(0,self.refresh_dirty)

    def read_gain(self,group):
        values=[v.get().strip() for v in self.gains[group]]
        if any(not v.isascii() or not v.isdecimal() for v in values):raise ValueError('AWB Gain 必须为正整数')
        result=tuple(int(v) for v in values)
        if any(not 1<=v<=MAX_GAIN for v in result):raise ValueError(f'Gain 范围 1～{MAX_GAIN}')
        return result

    def read_settings(self):
        if self.ccm_source.get()!=self._previous_source:self.refresh_link()
        current,target=self.read_gain('current'),self.read_gain('target')
        original=matrix_tuple(self.matrix_editor.matrix())
        mode=self.ccm_source.get()
        if mode==AUTO:
            destination=self.table.lookup(*target).ccm
        elif mode==SAME:
            destination=original
        elif mode==MANUAL:
            destination=matrix_tuple(self.target_editor.matrix())
        else:raise ValueError('未知目标 CCM 来源')
        settings=RetuneSettings(current,target,original,destination,(mode,self.table.fingerprint))
        settings.transform()
        return settings

    def is_dirty(self):
        messages=[editor.message_var.get() for editor in (self.matrix_editor,self.target_editor)]
        try:return self.read_settings()!=self.applied_settings
        except (ValueError,np.linalg.LinAlgError):return True
        finally:
            for editor,message in zip((self.matrix_editor,self.target_editor),messages):editor.message_var.set(message)

    def refresh_dirty(self):
        self._dirty_timer=None
        self.refresh_link()
        self.dirty_label.set('待应用' if self.is_dirty() else '')

    def refresh_link(self):
        if self._updating_link:return
        self._updating_link=True
        mode=self.ccm_source.get()
        messages=[editor.message_var.get() for editor in (self.matrix_editor,self.target_editor)]
        try:
            if mode!=self._previous_source:
                if self._previous_source==MANUAL:
                    self._manual_snapshot=self.target_editor.snapshot()
                if mode==MANUAL and self._manual_snapshot is not None:
                    self.target_editor.restore(self._manual_snapshot)
                self._previous_source=mode
            self.target_editor.set_readonly(mode!=MANUAL)
            if mode==AUTO:
                result=self.table.lookup(*self.read_gain('target'))
                self.last_lookup=result
                matrix=result.ccm
                text=f'≈ {result.cct:.0f} K'
                if result.warning:text+='\n'+result.warning
            elif mode==SAME:
                matrix=matrix_tuple(self.matrix_editor.matrix())
                text=''
                self.last_lookup=None
            elif mode==MANUAL:
                matrix=None;text='';self.last_lookup=None
            else:raise ValueError('未知 CCM 来源')
            if matrix is not None:
                try:unchanged=np.array_equal(self.target_editor.matrix(),matrix)
                except ValueError:unchanged=False
                if not unchanged:
                    self.target_editor.set_matrix(matrix)
            self.link_info.set(text)
            original=matrix_tuple(self.matrix_editor.matrix())
            original_note='估算值，非实测' if original==self._estimated_original else ''
            if original_note and self._original_estimate_warning and self._original_estimate_warning not in text:
                original_note+='\n'+self._original_estimate_warning
            self.original_info.set(original_note)
            try:
                if self.read_gain('current')==self.read_gain('target'):
                    destination=matrix if matrix is not None else matrix_tuple(self.target_editor.matrix())
                    if not np.array_equal(original,destination):
                        self.link_info.set((text+'\n' if text else '')+'Gain 相同，但原/目标 CCM 不同')
            except ValueError:pass
        except (ValueError,np.linalg.LinAlgError):
            self.link_info.set('待有效输入；当前矩阵尚未更新')
        finally:
            self._updating_link=False
            self.matrix_editor.message_var.set(messages[0])

    def lookup_details(self):
        result=self.last_lookup
        if result is None:return 'log-Gain 轨迹投影近似；不是硬件色温或插值规则'
        return (f'{result.lower} K → {result.upper} K；比例 {result.fraction:.4f}；'
                f'轨迹距离 {result.distance:.4f}\n近似模型；距离告警阈值 0.12（软件启发式）')

    def estimate_original(self):
        try:
            result=self.table.lookup(*self.read_gain('current'))
            self._estimated_original=result.ccm
            self._original_estimate_warning=result.warning
            self.matrix_editor.set_matrix(result.ccm)
            self.error.set('')
            self.refresh_dirty()
        except (ValueError,np.linalg.LinAlgError) as exc:self.error.set(str(exc))

    def reset_target(self):
        for target,current in zip(self.gains['target'],self.gains['current']):target.set(current.get())
        self.ccm_source.set(SAME)
        self.refresh_dirty()

    def open_table(self):
        from .awb_ccm_table_dialog import AWBCCMTableDialog
        if self.table_dialog is not None and self.table_dialog.winfo_exists():
            self.table_dialog.lift();return
        self.table_dialog=AWBCCMTableDialog(self,self.table,self.set_table)

    def set_table(self,table):
        candidate=CalibrationTable(tuple(table.points),table.name)
        try:self.calibration_store.save(candidate)
        except OSError as exc:raise OSError(f'标定表保存失败，当前表未更改：{exc}') from exc
        self.table=candidate
        self.storage_warning.set('')
        self.refresh_dirty()

    def open_images(self):
        if self.io_future is not None:return
        path=filedialog.askopenfilename(parent=self,title='导入 PotPlayer 截图',filetypes=[('PNG / JPEG','*.png *.jpg *.jpeg')])
        if not path:return
        self.status.set('正在读取截图…')
        self.io_future=self.executor.submit(read_color_image,path)
        self.later(30,self.poll_import)

    def poll_import(self):
        if not self.io_future.done():self.later(30,self.poll_import);return
        future,self.io_future=self.io_future,None
        try:self.set_document(future.result())
        except Exception as exc:self.error.set(str(exc))

    def set_document(self,document):
        self.document=document
        self.filename.set(Path(document.path).name)
        h,w=document.rgb.shape[:2];scale=min(1,1000/max(h,w))
        self.source=cv2.resize(document.rgb,(max(1,round(w*scale)),max(1,round(h*scale))),interpolation=cv2.INTER_AREA)
        self.output=self.source.copy()
        self.source_pil=self.make_display(self.source);self.output_pil=self.source_pil
        self.fit=True;self.drag=None;self.error.set('')
        self.request_preview(self.applied_settings)

    def make_display(self,rgb):
        rgb=np.clip(rgb,0,1)
        if self.document.alpha is not None:
            alpha=cv2.resize(self.document.alpha,(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_AREA)[...,None]
            rgb=rgb*alpha+(1-alpha)*.44
        return Image.fromarray(raster8(rgb))

    def apply(self):
        try:settings=self.read_settings()
        except (ValueError,np.linalg.LinAlgError) as exc:self.error.set(str(exc));return
        self.error.set('')
        if self.document is None:
            self.applied_settings=settings;self.refresh_dirty();return
        if self.future is None and settings==self.applied_settings and self._shown_revision==self.revision:
            self.refresh_dirty();return
        self.request_preview(settings)

    def request_preview(self,settings):
        self.requested_settings=settings;self.revision+=1
        self.status.set('正在更新 AWB 预览…');self.schedule_draw()
        if self.future is None:self.start_preview()

    def start_preview(self):
        revision,source,settings=self.revision,self.source,self.requested_settings
        self._running_revision=revision
        self.future=self.executor.submit(lambda:(revision,settings,retune_screenshot(source,settings)))
        self.later(30,self.poll_preview)

    def poll_preview(self):
        if not self.future.done():self.later(30,self.poll_preview);return
        future,self.future=self.future,None
        try:
            revision,settings,result=future.result()
            if revision!=self.revision:self.start_preview();return
            if not np.all(np.isfinite(result)):raise ValueError('输出存在 NaN/Infinity')
            self.output=result;self.output_pil=self.make_display(result)
            self.applied_settings=settings;self._shown_revision=revision
            outside=np.mean(np.any((result<0)|(result>1),axis=-1))*100
            self.status.set(f'近似预览 · 输出 sRGB · 超范围像素 {outside:.2f}% · {self.document.note}')
            self.refresh_dirty();self.schedule_draw()
        except Exception as exc:
            if self._running_revision!=self.revision:self.start_preview()
            else:self.error.set(str(exc))

    def preview_processor(self):
        settings=self.applied_settings
        return lambda pixels:retune_screenshot(pixels,settings)

    def press(self,event):
        if self.document is None:return 'break'
        if self.mode.get()=='滑动对比' and abs(event.x-self.canvas.winfo_width()*self.divider)<9:
            self.drag=('split',)
        else:
            self.drag=None
        return 'break'

    def export(self):
        if self.document is None or self.io_future is not None:return
        if self.future is not None:self.error.set('请等待当前应用完成后再导出');return
        if self.is_dirty():self.error.set('存在未应用参数，请先点击“应用”再导出');return
        path=filedialog.asksaveasfilename(parent=self,title='导出 AWB 结果 · sRGB',defaultextension='.png',filetypes=[('PNG 8-bit','*.png'),('TIFF 16-bit','*.tif *.tiff')])
        if not path:return
        document,settings=self.document,self.applied_settings
        self.io_future=self.executor.submit(export_processed_image,path,document,lambda pixels:retune_screenshot(pixels,settings))
        self.status.set('正在导出完整图像…');self.later(30,self.poll_export)

    def poll_export(self):
        if not self.io_future.done():self.later(30,self.poll_export);return
        future,self.io_future=self.io_future,None
        try:future.result();self.status.set('导出完成 · sRGB')
        except Exception as exc:self.error.set(str(exc))

    def destroy(self):
        self.closed=True
        self.cancel_detail()
        if self.table_dialog is not None and self.table_dialog.winfo_exists():self.table_dialog.destroy()
        for var,trace in self._traces:var.trace_remove('write',trace)
        for var,trace in self._status_traces:var.trace_remove('write',trace)
        for identifier in list(self._timers):self.after_cancel(identifier)
        self._timers.clear();self.executor.shutdown(wait=False,cancel_futures=True)
        super().destroy()
