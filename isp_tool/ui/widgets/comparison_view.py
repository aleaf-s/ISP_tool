"""Shared viewport-bounded before/after rendering and navigation."""
import math
from threading import Event
from concurrent.futures import CancelledError
from PIL import Image, ImageTk
from ...grading.model import raster8
from ...grading.viewport import render_viewport


class ComparisonViewMixin:
    def cancel_detail(self):
        if getattr(self, '_detail_cancel', None) is not None:
            self._detail_cancel.set()

    def clear_detail(self):
        self.cancel_detail()
        self._detail_wanted_key = self._detail_args = None
        self._detail_key = self._detail_views = None
        if getattr(self, '_detail_debounce', None) is not None:
            self.after_cancel(self._detail_debounce)
            self._timers.discard(self._detail_debounce)
            self._detail_debounce = None

    def request_detail(self, key, size):
        if key != getattr(self, '_detail_wanted_key', None):
            self.cancel_detail()
            self._detail_wanted_key = key
            self._detail_args = (self.document, self.preview_processor(), self.source_pil.size,
                                 self.zoom, tuple(self.offset), size)
            if getattr(self, '_detail_debounce', None) is not None:
                self.after_cancel(self._detail_debounce)
                self._timers.discard(self._detail_debounce)
            self._detail_debounce = self.later(150, self.start_detail)

    def start_detail(self):
        self._detail_debounce = None
        if self.closed or getattr(self, '_detail_future', None) is not None:
            return
        key = self._detail_wanted_key
        if key is None or self.document is None or self.document.document_id != key[0] or self.revision != key[1] or self._shown_revision != self.revision:
            return
        self._detail_cancel = Event()
        self._detail_running_key = self._detail_wanted_key
        self._detail_future = self.executor.submit(render_viewport, *self._detail_args, self._detail_cancel)
        self.later(30, self.poll_detail)

    def poll_detail(self):
        if not self._detail_future.done():
            self.later(30, self.poll_detail)
            return
        future, self._detail_future = self._detail_future, None
        try:
            views = future.result()
            if not self._detail_cancel.is_set() and self._detail_running_key == self._detail_wanted_key:
                self._detail_key, self._detail_views = self._detail_running_key, views
                self.schedule_draw()
        except CancelledError:
            pass
        except Exception as exc:
            if not self._detail_cancel.is_set():
                self.error.set(f'原分辨率预览失败：{exc}')
        if self._detail_running_key != self._detail_wanted_key and getattr(self, '_detail_debounce', None) is None:
            self.start_detail()

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
            self.clear_detail()
            self.canvas.create_text(30,30,anchor='nw',text=getattr(self,'empty_text','导入彩色图像，然后启用“取色”添加控制点'),fill='white')
            return
        w,h=max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
        side=self.mode.get()=='左右并排'
        pw=max(1,w//2) if side else w
        iw,ih=self.source_pil.size
        if self.fit:
            self.zoom=min(pw/iw,h/ih)
        # Fixed image centre: no pointer-following zoom or drag-to-pan.
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
        detail_ready = False
        if ready:
            key = (self.document.document_id, self.revision, self.enabled.get(), pw, h,
                   self.zoom, tuple(self.offset))
            self.request_detail(key, (pw,h))
            detail_ready = key == getattr(self, '_detail_key', None)
            if detail_ready:
                cached_before, cached_after = self._detail_views
                before = cached_before.copy()
                after = cached_before if self.hold_original or not self.enabled.get() else cached_after
        else:
            self.cancel_detail()
        decorator=getattr(self,'decorate_comparison_views',None)
        if decorator is not None:
            before,after=decorator(before,after)
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
        self.canvas.create_text(10,h-10,anchor='sw',text='原分辨率预览' if detail_ready else '快速预览…',fill='white')
        if (getattr(self,'method',None) is not None and self.method.get()=='CLUT 调色'
                and self.state_for(self.document).clut.show_influence and not self.hold_original):
            self.canvas.create_text(10,34,anchor='nw',text='橙色：选中颜色邻域（预估，不写入导出）',fill='#ffcc80')

    def coordinates(self,event):
        w=max(1,self.canvas.winfo_width())
        pw=w//2 if self.mode.get()=='左右并排' else w
        local=event.x%max(1,pw) if self.mode.get()=='左右并排' else event.x
        return (local-self.offset[0])/self.zoom,(event.y-self.offset[1])/self.zoom,local

    def motion(self,event):
        if self.drag:
            if self.drag[0]=='split': self.divider=max(.02,min(.98,event.x/max(1,self.canvas.winfo_width())))
            self.schedule_draw()
        return 'break'

    def wheel(self,event):
        if self.document is not None:
            self.fit=False
            self.zoom=max(.02,min(32,self.zoom*(1.15 if event.delta>0 else 1/1.15)))
            self.schedule_draw()
        return 'break'

    def hover(self,event):
        if self.source is None: return
        x,y,_=self.coordinates(event)
        if 0<=x<self.source.shape[1] and 0<=y<self.source.shape[0]:
            x=int(x*self.document.rgb.shape[1]/self.source.shape[1])
            y=int(y*self.document.rgb.shape[0]/self.source.shape[0])
            source=self.document.rgb[y:y+1,x:x+1]
            ready=self._shown_revision==self.revision
            result=self.preview_processor()(source) if ready and self.enabled.get() else source
            before=tuple(raster8(source)[0,0].tolist())
            after=tuple(raster8(result)[0,0].tolist())
            self.status.set(f'原图 ({x},{y}) · Before RGB {before} · After RGB {after} /255' + ('' if ready else ' · 正在更新'))
