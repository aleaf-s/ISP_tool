"""Sample-defined HSV TXT lattice; software interpolation is not PQTools' solver.

H/S targets are established by paired files. The third field remains opaque;
nonzero values round-trip but cannot be rendered or baked to a device CLUT.
"""
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
import re
import cv2
import numpy as np

HUES = tuple(float(x) for x in range(0,361,15))
SATS = (0.,.106,.213,.319,.425,.532,.638,.745,.851,.957,1.064,1.170)
VALUES = tuple(x/8 for x in range(9))
SHAPE = (9,25,12)
COUNT = 2700
CLUT_GAIN_SCALE = 512
DEFAULT_GAINS = (512,512,512)


def identity_targets():
    v,h,s=np.meshgrid(VALUES,HUES,SATS,indexing='ij')
    return np.stack((h,s,np.zeros_like(v)),axis=-1)


IDENTITY=tuple(identity_targets().ravel())


@dataclass(frozen=True)
class HSVPlane:
    dh: tuple
    ds: tuple


@dataclass(frozen=True)
class HSVGrid:
    targets: tuple = IDENTITY
    base_words: tuple = ()
    original_text: str = ''
    original_targets: tuple = ()
    prefix: str = ''
    strength: float = 1.
    enabled: bool = True
    gains: tuple = DEFAULT_GAINS

    def __post_init__(self):
        if not isinstance(self.enabled,bool):raise ValueError('CLUT 使能需要布尔值')
        gains=np.asarray(self.gains)
        if (gains.shape!=(3,) or gains.dtype.kind not in 'iu'
                or np.any(gains<0) or np.any(gains>4095)):
            raise ValueError('gain_r / gain_g / gain_b 需要 0～4095 的整数')
        object.__setattr__(self,'gains',tuple(int(v) for v in gains))
        if not np.isfinite(self.strength) or not 0<=self.strength<=2:
            raise ValueError('整体强度范围为 0～2')
        a=np.asarray(self.targets,float)
        if a.shape!=(COUNT*3,) or not np.all(np.isfinite(a)):
            raise ValueError('HSV 需要 2700 条有限的三分量目标记录')
        a=a.reshape(-1,3)
        # Axis endpoints describe INPUT coordinates, not target bounds.
        # Keep finite opaque fields intact; never interpret or clip them here.
        if np.any(a[:,1]<0):
            raise ValueError('HSV 目标饱和度不能为负值')
        if self.base_words:raise ValueError('三维 HSV 工程不能混入设备表；请分别导入')
        object.__setattr__(self,'targets',tuple(a.ravel().tolist()))

    @property
    def preview_supported(self):
        return not np.any(np.asarray(self.targets).reshape(-1,3)[:,2]!=0)

    def plane(self,index):
        a=np.asarray(self.targets).reshape(*SHAPE,3)[index]
        return HSVPlane(tuple((a[...,0]-np.asarray(HUES)[:,None]).ravel()),
                        tuple((a[...,1]-np.asarray(SATS)[None,:]).ravel()))

    def patch(self,component,row,column,block,index=4):
        if component not in ('dh','ds'):raise ValueError('未知 HSV 分量')
        b=np.asarray(block,float)
        if b.ndim!=2 or not b.size or not np.all(np.isfinite(b)):raise ValueError('需要有限的矩形数字区域')
        h,w=b.shape
        if not 0<=index<9 or not 0<=row<25 or not 0<=column<12 or row+h>25 or column+w>12:
            raise ValueError('区域超出 HSV 网格')
        if component=='dh' and np.any(abs(b)>180):raise ValueError('ΔHue 范围 ±180°')
        if column==0 and np.any(b[:,0]!=0):raise ValueError('S=0 中性轴锁定')
        a=np.asarray(self.targets).reshape(*SHAPE,3).copy()
        channel=0 if component=='dh' else 1
        axis=np.asarray(HUES[row:row+h])[:,None] if component=='dh' else np.asarray(SATS[column:column+w])[None,:]
        target=a[index,row:row+h,column:column+w,channel]
        changed=b!=(target-axis)
        target[changed]=(b+axis)[changed]
        return replace(self,targets=tuple(a.ravel()))

    def edit(self,index,row,column,dh,ds,radius=0.,smoothness=1.):
        self.patch('dh',row,column,[[dh]],index).patch('ds',row,column,[[ds]],index)
        weight=plane_weights(row,column,radius,smoothness)
        p=self.plane(index);oldh=np.array(p.dh).reshape(25,12);olds=np.array(p.ds).reshape(25,12)
        step=(dh-oldh[row,column]+180)%360-180
        newh=oldh+step*weight;news=olds+(ds-olds[row,column])*weight
        newh[weight>0]=(newh[weight>0]+180)%360-180
        newh[row,column]=dh;news[row,column]=ds
        # Patch only affected cells so imported nonzero neutral parameters and
        # unwrapped hue values are not rewritten by an unrelated edit.
        a=np.asarray(self.targets).reshape(*SHAPE,3).copy();active=weight>0
        if dh!=oldh[row,column]:a[index,:,:,0][active]=(newh+np.asarray(HUES)[:,None])[active]
        if ds!=olds[row,column]:a[index,:,:,1][active]=(news+np.asarray(SATS)[None,:])[active]
        return replace(self,targets=tuple(a.ravel()))

    def reset(self):
        # Reset only understood H/S targets. Opaque fields are never discarded.
        a=np.asarray(self.targets).reshape(*SHAPE,3).copy()
        a[...,:2]=identity_targets()[...,:2]
        return replace(self,targets=tuple(a.ravel()))

    def effective(self):
        """Bake the independent coefficient once for both preview and TXT export."""
        if self.strength==1:return self
        a=np.asarray(self.targets).reshape(*SHAPE,3).copy();base=identity_targets()
        dh=(a[...,0]-base[...,0]+180)%360-180
        a[...,0]=base[...,0]+dh*self.strength
        a[...,1]=np.maximum(0,base[...,1]+(a[...,1]-base[...,1])*self.strength)
        return replace(self,targets=tuple(a.ravel()),strength=1.)

    def cover_center(self):
        """Use the edited center H/S plane at every V, retaining opaque fields."""
        a=np.asarray(self.targets).reshape(*SHAPE,3).copy()
        a[...,:2]=a[4,...,:2].copy()
        return replace(self,targets=tuple(a.ravel()))


@dataclass
class HSVState:
    """Per-image HSV drafts and applied image parameters; no device LUT source."""
    grid: HSVGrid = field(default_factory=HSVGrid)
    applied_grid: HSVGrid = field(default_factory=HSVGrid)
    undo_stack: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)
    selected: tuple = (0,4)
    selection_end: tuple = (0,4)
    drafts: dict = field(default_factory=dict)
    tab: str = '色轮'
    value: float = .5
    radius: float = 0.
    smoothness: float = 1.
    show_influence: bool = False
    sample_rgb: object = None
    slice_index: int = 4
    hsv_path: str = ''
    applied_hsv_path: str = ''
    import_note: str = ''
    strength_draft: object = None
    gain_draft: object = None

    def pending(self):
        return bool(self.drafts or self.strength_draft is not None or self.gain_draft is not None or self.grid != self.applied_grid)

    def replace(self,grid):
        if grid==self.grid:return False
        self.undo_stack.append(self.grid);self.undo_stack=self.undo_stack[-100:]
        self.redo_stack.clear();self.grid=grid
        return True

    def travel(self,redo=False):
        source,target=(self.redo_stack,self.undo_stack) if redo else (self.undo_stack,self.redo_stack)
        if not source:return False
        target.append(self.grid);self.grid=source.pop();self.drafts.clear();self.strength_draft=None;self.gain_draft=None
        return True


def plane_weights(row,column,radius=0.,smoothness=1.):
    if not 0<=row<25 or not 0<=column<12:raise ValueError('节点越界')
    if not np.isfinite(radius) or not 0<=radius<=6 or not np.isfinite(smoothness) or not 0<=smoothness<=1:
        raise ValueError('邻域 0～6；平滑强度 0～1')
    rr,cc=np.indices((25,12));distance=np.hypot(rr-row,cc-column)
    if radius==0:w=(distance==0).astype(float)
    else:
        t=np.clip(1-distance/radius,0,1);w=(1-smoothness)*t+smoothness*t*t*(3-2*t)
    w[:,0]=0
    return w


def locate(rgb):
    hsv=cv2.cvtColor(np.asarray(rgb,np.float32).reshape(1,1,3),cv2.COLOR_RGB2HSV)[0,0]
    h,s,v=map(float,hsv)
    vi=int(np.argmin(abs(np.asarray(VALUES)-v)))
    if s<.02 or v<.005:return vi,0,0
    return vi,int(np.argmin(abs(np.asarray(HUES)-h))),int(np.argmin(abs(np.asarray(SATS)-s)))


def sample_field(hsv,field):
    """Trilinear sampling, exact sample axes; 0/360 boundary records preserved."""
    coords=(np.clip(hsv[...,2],0,1),hsv[...,0]%360,np.clip(hsv[...,1],0,1.17))
    indices=[];fractions=[]
    for q,axis in zip(coords,(VALUES,HUES,SATS)):
        a=np.asarray(axis);i=np.clip(np.searchsorted(a,q,side='right')-1,0,len(a)-2)
        indices.append(i);fractions.append((q-a[i])/(a[i+1]-a[i]))
    result=np.zeros(hsv.shape[:-1],np.float64)
    f=np.asarray(field).reshape(SHAPE)
    for v in (0,1):
        for h in (0,1):
            for s in (0,1):
                bits=(v,h,s);weight=np.ones_like(result)
                for t,b in zip(fractions,bits):weight*=t if b else 1-t
                result+=weight*f[indices[0]+v,indices[1]+h,indices[2]+s]
    return result


def influence(hsv,index,row,column,radius,smoothness):
    f=np.broadcast_to(plane_weights(row,column,radius,smoothness),SHAPE)
    return sample_field(hsv,f)


@lru_cache(maxsize=4)
def build_hsv_clut(grid):
    grid=grid.effective()
    if not grid.preview_supported:
        raise ValueError('HSV 含非零第三字段，单位未确认；可原样导出 HSV，不能预览或生成设备 CLUT')
    axis=np.linspace(0,1,33,dtype=np.float32)
    rgb=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1)
    if not grid.enabled or grid.gains==(0,0,0) or grid.targets==IDENTITY:
        rgb.setflags(write=False);return rgb
    hsv=cv2.cvtColor(rgb.reshape(-1,1,3),cv2.COLOR_RGB2HSV)
    target=np.asarray(grid.targets).reshape(*SHAPE,3)
    dh=(target[...,0]-np.asarray(HUES)[None,:,None]+180)%360-180
    ds=target[...,1]-np.asarray(SATS)[None,None,:]
    out=hsv.copy();out[...,0]=(hsv[...,0]+sample_field(hsv,dh))%360
    out[...,1]=np.clip(hsv[...,1]+sample_field(hsv,ds),0,1)
    out[...,1]=np.where(hsv[...,1]==0,0,out[...,1])
    result=np.clip(cv2.cvtColor(out,cv2.COLOR_HSV2RGB).reshape(rgb.shape),0,1)
    # CLUT Attr scales RGB displacement, not H/S parameters or absolute RGB.
    # Keep vertices outside gamut until apply_clut interpolates and clips pixels.
    if grid.gains!=DEFAULT_GAINS:
        result=rgb+(result-rgb)*(np.asarray(grid.gains,np.float32)/CLUT_GAIN_SCALE)
    result.setflags(write=False);return result


def load_hsv(path):
    p=Path(path)
    if p.stat().st_size>1024*1024:raise ValueError('HSV 文件超过 1 MiB')
    original_text=p.read_bytes().decode('utf-8')
    text=original_text.removeprefix('\ufeff')
    if text.count('HSV Lut:')!=1:raise ValueError('需要 HSV Lut 文件头')
    prefix,body=text.split('HSV Lut:',1)
    for line in prefix.splitlines():
        if line.strip():
            try:fields=[float(v) for v in line.split(',')]
            except ValueError:raise ValueError('不支持的 HSV 前缀')
            if len(fields)!=10 or not np.all(np.isfinite(fields)):raise ValueError('HSV RGB 对前缀须为十个有限数值')
    for label,expected in (('Hue',HUES[:-1]),('Sat',SATS),('Bri',VALUES)):
        match=re.search(label+r' Tab (\d+)\s*:\s*([^\r\n]+)',body)
        if not match:raise ValueError('缺少 HSV 轴定义')
        values=tuple(float(v.strip()) for v in match[2].split(',') if v.strip())
        if len(values)!=int(match[1]) or values!=expected:raise ValueError('当前仅支持海思样例 24/12/9 轴定义')
        body=body[:match.start()]+body[match.end():]
    matches=list(re.finditer(r'\{([^{}]+)\}\s*;',body))
    if len(matches)!=COUNT:raise ValueError('HSV 需要 2700 条记录（含 360° 接缝）')
    if re.sub(r'\{[^{}]+\}\s*;','',body).strip():raise ValueError('HSV 记录中有未知内容')
    a=np.empty((*SHAPE,3));seen=set()
    for match in matches:
        values=[float(v) for v in match[1].split(',')]
        if len(values)!=6 or not np.all(np.isfinite(values)):raise ValueError('每条 HSV 记录需要六个有限数值')
        h,s,v=values[:3]
        if h!=int(h) or s!=int(s) or v!=int(v) or not 0<=h<25 or not 0<=s<12 or not 0<=v<9:
            raise ValueError('HSV 索引越界或非整数')
        key=(int(v),int(h),int(s))
        if key in seen:raise ValueError('重复 HSV 节点')
        seen.add(key);a[key]=values[3:]
    data=tuple(a.ravel())
    return HSVGrid(data,original_text=original_text,original_targets=data,prefix=prefix)


def export_hsv(path,grid):
    from .clut import atomic_text
    if not isinstance(grid,HSVGrid):raise ValueError('请选择三维 HSV 模式；旧 HS 网格不能伪装为海思工程')
    grid=grid.effective()
    if grid.original_text and grid.original_targets:
        # Preserve BOM, line endings, record order, whitespace, prefix and
        # every untouched numeric token. Only changed target fields are patched.
        old=np.asarray(grid.original_targets).reshape(*SHAPE,3)
        current=np.asarray(grid.targets).reshape(*SHAPE,3)
        prefix,body=grid.original_text.split('HSV Lut:',1)
        def patch_record(match):
            fields=match.group(1).split(',')
            h,s,v=(int(float(x)) for x in fields[:3])
            for component in range(3):
                if current[v,h,s,component]!=old[v,h,s,component]:
                    fields[component+3]=re.sub(r'\S+',repr(float(current[v,h,s,component])),fields[component+3],count=1)
            return '{'+','.join(fields)+'}'+match.group(2)
        body=re.sub(r'\{([^{}]+)\}(\s*;)',patch_record,body)
        atomic_text(path,prefix+'HSV Lut:'+body,newline='');return
    lines=[grid.prefix+'HSV Lut:']
    for label,axis in (('Hue',HUES[:-1]),('Sat',SATS),('Bri',VALUES)):
        lines.append(f'{label} Tab {len(axis)} : '+','.join(f'{v:.12g}' for v in axis)+',')
    a=np.asarray(grid.targets).reshape(*SHAPE,3)
    for v in range(9):
        for h in range(25):
            for s in range(12):
                fields=', '.join(repr(float(x)) for x in a[v,h,s])
                lines.append(f'{{{h:2d}, {s:2d}, {v:2d}, {fields}}};')
    atomic_text(path,'\n'.join(lines)+'\n',newline='')
