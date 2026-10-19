"""Software HS editor and RGB CLUT. Not a HiSilicon register format.

Encoded sRGB, H degrees, S/V 0..1. Hue delta is signed degrees; saturation
delta is additive. 24x9 HS anchors, periodic smoothstep interpolation.
RGB compilation uses 33 uniform nodes and tetrahedral interpolation.
"""
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import json
import os
import tempfile
import cv2
import numpy as np

HUES = tuple(float(v) for v in range(0, 360, 15))
SATS = tuple(float(v) for v in np.linspace(0, 1, 9))
SHAPE = (24, 9)
ZEROS = (0.,) * (24*9)
SPACE = 'sRGB encoded; D65'
UNITS = {'hue': 'degree', 'saturation': '0..1', 'value': '0..1',
         'delta_hue': 'signed degree', 'delta_saturation': 'additive 0..1'}


@dataclass(frozen=True)
class HSGrid:
    dh: tuple = ZEROS
    ds: tuple = ZEROS
    base_words: tuple = ()

    def __post_init__(self):
        if self.base_words:
            from .hisi_clut import unpack_words
            unpack_words(self.base_words)
        for name, limit in (('dh', 180.), ('ds', 1.)):
            a = np.asarray(getattr(self, name), dtype=np.float64)
            if a.shape != (216,) or not np.all(np.isfinite(a)) or np.any(np.abs(a)>limit):
                raise ValueError(f'{name} 必须包含 216 个有限数值，范围 ±{limit:g}')
            if np.any(a.reshape(SHAPE)[:,0] != 0):
                raise ValueError('S=0 中性轴锁定，Delta 必须为 0')
            object.__setattr__(self, name, tuple(a.tolist()))

    def patch(self, component, row, column, block):
        if component not in ('dh', 'ds'):
            raise ValueError('未知 CLUT 分量')
        block = np.asarray(block, dtype=float)
        if block.ndim != 2 or not block.size:
            raise ValueError('请粘贴矩形数字区域')
        h,w = block.shape
        if not 0<=row<24 or not 0<=column<9 or row+h>24 or column+w>9:
            raise ValueError('粘贴区域超出网格')
        a = np.array(getattr(self, component)).reshape(SHAPE)
        a[row:row+h,column:column+w] = block
        return HSGrid(**{**dict(dh=self.dh, ds=self.ds, base_words=self.base_words), component:tuple(a.ravel())})


@dataclass
class CLUTState:
    grid: HSGrid = field(default_factory=HSGrid)
    applied_grid: HSGrid = field(default_factory=HSGrid)
    undo_stack: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)
    selected: tuple = (0, 4)
    selection_end: tuple = (0, 4)
    drafts: dict = field(default_factory=dict)
    tab: str = '色轮'
    value: float = .8
    radius: float = 0.
    smoothness: float = 1.
    show_influence: bool = False
    sample_rgb: object = None
    slice_index: int = 4
    device_grid: object = None
    device_path: str = ''
    hsv_path: str = ''
    preview_source: str = 'editor'
    applied_source: str = 'editor'
    applied_editor_grid: object = None
    applied_device_grid: object = None
    applied_device_path: str = ''
    applied_hsv_path: str = ''
    import_note: str = ''

    def preview_grid(self):
        return self.device_grid if self.preview_source == 'device' else self.grid

    def pending(self):
        return bool(self.drafts or self.preview_source != self.applied_source
                    or self.preview_grid() != self.applied_grid)

    def replace(self, grid):
        if grid == self.grid:return False
        self.undo_stack.append(self.grid);self.undo_stack=self.undo_stack[-100:]
        self.redo_stack.clear();self.grid=grid
        return True

    def travel(self, redo=False):
        source, target = (self.redo_stack,self.undo_stack) if redo else (self.undo_stack,self.redo_stack)
        if not source:return False
        target.append(self.grid);self.grid=source.pop();self.drafts.clear()
        return True


def sample_hs_field(hsv, field):
    """Same periodic interpolation for the colour model and influence preview."""
    h,s = hsv[...,0] % 360, np.clip(hsv[...,1],0,1)
    hp,sp = h/15, s*8
    hi,si = np.floor(hp).astype(int)%24, np.minimum(np.floor(sp).astype(int),7)
    ht,st = hp-np.floor(hp), sp-si
    ht,st = ht*ht*(3-2*ht), st*st*(3-2*st)
    a=np.asarray(field).reshape(SHAPE)
    return ((a[hi,si]*(1-ht)+a[(hi+1)%24,si]*ht)*(1-st)
            +(a[hi,si+1]*(1-ht)+a[(hi+1)%24,si+1]*ht)*st)


def neighbor_weights(row,column,radius=0.,smoothness=1.):
    if not 0<=row<24 or not 0<=column<9:raise ValueError('节点超出范围')
    if not np.isfinite(radius) or not 0<=radius<=6:raise ValueError('邻域范围：0…6 格')
    if not np.isfinite(smoothness) or not 0<=smoothness<=1:raise ValueError('平滑强度：0…1')
    if column==0:return np.zeros(SHAPE)
    rr,cc=np.indices(SHAPE);dh=np.minimum(abs(rr-row),24-abs(rr-row))
    distance=np.hypot(dh,cc-column)
    if radius==0:weights=(distance==0).astype(float)
    else:
        t=np.clip(1-distance/radius,0,1)
        weights=(1-smoothness)*t+smoothness*t*t*(3-2*t)
    weights[:,0]=0
    return weights


def edit_neighborhood(grid,row,column,dh,ds,radius=0.,smoothness=1.):
    # First validate the selected node, including the locked neutral axis.
    grid.patch('dh',row,column,[[dh]]).patch('ds',row,column,[[ds]])
    weights=neighbor_weights(row,column,radius,smoothness)
    k=row*9+column
    # Use the shortest hue displacement across the -180/+180 seam.
    hue_step=(dh-grid.dh[k]+180)%360-180
    hue=np.asarray(grid.dh).reshape(SHAPE)+hue_step*weights
    active=weights>0
    hue[active]=(hue[active]+180)%360-180
    sat=np.asarray(grid.ds).reshape(SHAPE)+(ds-grid.ds[k])*weights
    # Do not silently saturate an existing neighboring edit.
    if np.any(abs(sat)>1+1e-12):raise ValueError('邻域 Sat 偏移超出 ±1，请减小调整量或邻域范围')
    sat=np.clip(sat,-1,1)  # floating-point epsilon only
    hue[row,column]=dh;sat[row,column]=ds
    return HSGrid(tuple(hue.ravel()),tuple(sat.ravel()),grid.base_words)


def locate_rgb_node(rgb):
    value=np.asarray(rgb,np.float32).reshape(1,1,3)
    if not np.all(np.isfinite(value)) or np.any((value<0)|(value>1)):raise ValueError('RGB 范围 0…1')
    h,s,v=cv2.cvtColor(value,cv2.COLOR_RGB2HSV)[0,0]
    if s<.02 or v<.005:return 0,0
    return int(np.floor(h/15+.5))%24,min(8,int(np.floor(s*8+.5)))


def map_hsv(hsv, grid):
    result = np.asarray(hsv, np.float32).copy()
    s=np.clip(result[...,1],0,1)
    # Both fields must be sampled in the original, not modified, HS domain.
    dh=sample_hs_field(result,grid.dh);ds=sample_hs_field(result,grid.ds)
    result[...,0]+=dh;result[...,1]+=ds
    result[...,0]%=360
    result[...,1]=np.clip(result[...,1],0,1)
    result[...,1]=np.where(s==0,0,result[...,1])
    return result


@lru_cache(maxsize=4)
def build_clut(grid):
    from .hsv_grid import HSVGrid, build_hsv_clut
    if isinstance(grid,HSVGrid):return build_hsv_clut(grid)
    if grid.base_words:
        from .hisi_clut import unpack_words
        axis17=np.linspace(0,1,17,dtype=np.float32)
        base=np.stack(np.meshgrid(axis17,axis17,axis17,indexing='ij'),axis=-1)
        imported=base+unpack_words(grid.base_words).astype(np.float32)/1023
        if grid.dh==ZEROS and grid.ds==ZEROS:
            imported.setflags(write=False)
            return imported
        # Add software HS displacement in the ORIGINAL input domain. Do not
        # pretend that an arbitrary 3-D device LUT was inverted to a 2-D grid.
        axis=np.linspace(0,1,33,dtype=np.float32)
        rgb=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1)
        result=np.clip(apply_clut(rgb,imported)+build_clut(HSGrid(grid.dh,grid.ds))-rgb,0,1)
        result.setflags(write=False)
        return result
    axis=np.linspace(0,1,33,dtype=np.float32)
    rgb=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1)
    if grid==HSGrid():
        rgb.setflags(write=False);return rgb
    hsv=cv2.cvtColor(rgb.reshape(-1,1,3),cv2.COLOR_RGB2HSV)
    result=cv2.cvtColor(map_hsv(hsv,grid),cv2.COLOR_HSV2RGB).reshape(rgb.shape)
    diagonal=np.arange(33)
    result[diagonal,diagonal,diagonal]=rgb[diagonal,diagonal,diagonal]
    result=np.clip(result,0,1);result.setflags(write=False)
    return result


def apply_clut(image, lut):
    """Tetrahedral displacement sampling; preserves the identity/neutral axis."""
    src=np.clip(np.asarray(image,np.float32),0,1)
    flat=src.reshape(-1,3);n=len(lut)-1
    p=flat*n;base=np.minimum(np.floor(p).astype(np.int32),n-1)
    f=p-base;order=np.argsort(-f,axis=1,kind='stable')
    sorted_f=np.take_along_axis(f,order,axis=1)
    weights=np.column_stack((1-sorted_f[:,0],sorted_f[:,0]-sorted_f[:,1],
                             sorted_f[:,1]-sorted_f[:,2],sorted_f[:,2]))
    result=flat.copy();vertex=base.copy();rows=np.arange(len(flat))
    for k in range(4):
        if k:vertex[rows,order[:,k-1]]+=1
        displacement=lut[vertex[:,0],vertex[:,1],vertex[:,2]]-vertex.astype(np.float32)/n
        result+=displacement*weights[:,k,None]
    return np.clip(result.reshape(src.shape),0,1)


def atomic_json(path, payload):
    atomic_text(path,json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')))


def atomic_text(path, text, *, newline=None):
    path=Path(path)
    descriptor, temporary=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8',newline=newline) as stream:
            stream.write(text)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def read_json(path):
    if Path(path).stat().st_size>16*1024*1024:raise ValueError('文件过大（上限 16 MiB）')
    with open(path,encoding='utf-8') as stream:payload=json.load(stream)
    if not isinstance(payload,dict):raise ValueError('无效的 CLUT JSON')
    return payload


def save_parameters(path, grid, source=''):
    if grid.base_words:raise ValueError('导入的设备表请使用 TXT 导出，不能保存为旧版 JSON 网格')
    atomic_json(path,dict(format='isp-hs-clut-parameters',version=1,mode='clut',
        source=source,space=SPACE,units=UNITS,hues=HUES,saturations=SATS,
        interpolation='periodic smoothstep HS',dh=np.array(grid.dh).reshape(SHAPE).tolist(),
        ds=np.array(grid.ds).reshape(SHAPE).tolist(),rgb_nodes=33,rgb_interpolation='tetrahedral'))


def load_parameters(path):
    p=read_json(path)
    if (p.get('format')!='isp-hs-clut-parameters' or p.get('version')!=1 or p.get('mode')!='clut'
            or p.get('space')!=SPACE or p.get('units')!=UNITS
            or p.get('hues')!=list(HUES) or p.get('saturations')!=list(SATS)
            or p.get('interpolation')!='periodic smoothstep HS' or p.get('rgb_nodes')!=33
            or p.get('rgb_interpolation')!='tetrahedral'):
        raise ValueError('不支持的参数格式、单位或网格；不是 HiSilicon 文件读取器')
    a,b=np.asarray(p.get('dh'),float),np.asarray(p.get('ds'),float)
    if a.shape!=SHAPE or b.shape!=SHAPE:raise ValueError('Delta 表尺寸必须为 24×9')
    return HSGrid(tuple(a.ravel()),tuple(b.ravel())),str(p.get('source',''))


def export_clut(path, grid):
    lut=build_clut(grid)
    payload=dict(format='isp-rgb-clut',version=1,space=SPACE,nodes=33,
        axes='RGB',fastest_axis='B',channels='RGB',encoding='float32 0..1',
        interpolation='tetrahedral',domain=[0,1],hardware_compatible=False,
        data=lut.reshape(-1,3).tolist())
    # Validate the serialized representation before replacing the destination.
    decoded=decode_clut(json.loads(json.dumps(payload,allow_nan=False)))
    if not np.array_equal(decoded,lut):raise ValueError('CLUT 序列化校验失败')
    atomic_json(path,payload)


def decode_clut(p):
    expected=dict(format='isp-rgb-clut',version=1,space=SPACE,nodes=33,axes='RGB',
                  fastest_axis='B',channels='RGB',encoding='float32 0..1',
                  interpolation='tetrahedral',domain=[0,1],hardware_compatible=False)
    if any(p.get(k)!=v for k,v in expected.items()):raise ValueError('不支持的 RGB CLUT 格式')
    a=np.asarray(p.get('data'),np.float32)
    if a.shape!=(33**3,3) or not np.all(np.isfinite(a)) or np.any((a<0)|(a>1)):
        raise ValueError('CLUT 尺寸或数值范围错误')
    return a.reshape(33,33,33,3)


def load_clut(path):
    return decode_clut(read_json(path))
