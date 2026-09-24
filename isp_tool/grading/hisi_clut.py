"""5508-word CLUT adapter, matched against the supplied TXT structure.

Reference: Huawei CANN hi_isp_clut_lut (900beta2 / ispdevapi_0276).
File packing is verifiable; input DN scale, CLUT gain, interpolation and target
chip compatibility require device confirmation. Never silently saturate deltas.
"""
from functools import lru_cache
from pathlib import Path
import re
import numpy as np
from .clut import HSGrid, ZEROS, build_clut, apply_clut, atomic_text


@lru_cache(maxsize=1)
def addresses():
    counters=[0]*8;indices=[];positions=[]
    for g in range(17):
        for b in range(17):
            for r in range(17):
                group=(r&1)+2*(b&1)+4*(g&1)
                address=(0 if group<4 else 2916)+4*counters[group]+group%4
                counters[group]+=1
                indices.append((r,g,b));positions.append(address)
    return np.array(indices),np.array(positions)


def pack_deltas(deltas):
    a=np.asarray(deltas)
    if a.shape!=(17,17,17,3) or not np.all(np.isfinite(a)) or np.any(a!=np.rint(a)) or np.any(np.abs(a)>511):
        raise ValueError('HiSilicon Delta RGB 必须是 17³×3 整数，范围 −511…511；未执行截断')
    indices,positions=addresses()
    values=a[indices[:,0],indices[:,1],indices[:,2]].astype(np.int64)&1023
    words=np.zeros(5508,np.uint32)
    words[positions]=values[:,0]|(values[:,1]<<10)|(values[:,2]<<20)
    return words


def unpack_words(words):
    words=np.asarray(words)
    if words.shape!=(5508,) or not np.all(np.isfinite(words)) or np.any(words!=np.rint(words)) or np.any((words<0)|(words>2**30-1)):
        raise ValueError('文件必须有 5508 个 0…1073741823 整数')
    indices,positions=addresses();mask=np.ones(5508,bool);mask[positions]=False
    if np.any(words[mask]):raise ValueError('CLUT 填充位非零，格式与当前适配器不同')
    values=words[positions].astype(np.int64)
    fields=np.column_stack(tuple((values>>shift)&1023 for shift in (0,10,20)))
    fields=np.where(fields>=512,fields-1024,fields)
    if np.any(fields==-512):raise ValueError('−512 超出该适配格式允许范围')
    result=np.empty((17,17,17,3),np.int16)
    result[indices[:,0],indices[:,1],indices[:,2]]=fields
    return result


def read_words(path):
    if Path(path).stat().st_size>1024*1024:raise ValueError('CLUT TXT 文件过大')
    text=Path(path).read_text(encoding='utf-8-sig')
    if re.sub(r'[\d\s,]','',text):raise ValueError('CLUT TXT 含未知字符或文件头')
    tokens=[t.strip() for t in text.strip().rstrip(',').split(',')]
    if any(not t.isdigit() for t in tokens):raise ValueError('CLUT TXT 需要逗号分隔整数')
    words=np.array([int(t) for t in tokens],dtype=np.int64)
    unpack_words(words)
    return words


def quantize_grid(grid):
    axis=np.linspace(0,1,17,dtype=np.float32)
    rgb=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1)
    corrected=apply_clut(rgb,build_clut(grid))
    # Explicit export profile assumption: 10-bit full range and unit gain.
    # np.rint: round-half-to-even. Range checked before any packing/masking.
    delta=np.rint((corrected-rgb)*1023).astype(np.int32)
    pack_deltas(delta)
    return delta


def export_hisi(path,grid):
    if grid.base_words and grid.dh==ZEROS and grid.ds==ZEROS:
        words=np.asarray(grid.base_words,dtype=np.int64)
        delta=unpack_words(words)
    else:
        delta=quantize_grid(grid);words=pack_deltas(delta)
    if not np.array_equal(unpack_words(words),delta):raise ValueError('CLUT 打包校验失败')
    text='\n'.join(','.join(f'{int(v):11d}' for v in words[i:i+9])+',' for i in range(0,len(words),9))+'\n'
    axis=np.linspace(0,1,17,dtype=np.float32)
    base=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1)
    reconstructed=base+unpack_words(words).astype(np.float32)/1023
    axis33=np.linspace(0,1,33,dtype=np.float32)
    probes=np.stack(np.meshgrid(axis33,axis33,axis33,indexing='ij'),axis=-1)
    difference=np.abs(apply_clut(probes,reconstructed)-apply_clut(probes,build_clut(grid)))*255
    atomic_text(path,text)
    return dict(mean_code_error=float(difference.mean()),max_code_error=float(difference.max()))


def load_hisi(path):
    """Preserve all device words. HS edits start at zero as extra adjustments."""
    return HSGrid(base_words=tuple(int(v) for v in read_words(path)))


def inspect_hsv(path):
    """Structural audit only. Do not assume these records are HSV deltas."""
    if Path(path).stat().st_size>1024*1024:raise ValueError('HSV 文件过大')
    text=Path(path).read_text(encoding='utf-8-sig')
    axes={}
    for label in ('Hue','Sat','Bri'):
        match=re.search(label+r' Tab (\d+)\s*:\s*([^\n]+)',text)
        if not match:raise ValueError('缺少 HSV 轴定义')
        values=tuple(float(v.strip()) for v in match[2].split(',') if v.strip())
        if len(values)!=int(match[1]) or not np.all(np.isfinite(values)) or np.any(np.diff(values)<=0):raise ValueError('HSV 轴无效')
        axes[label]=values
    rows=np.array([[float(v) for v in row.split(',')] for row in re.findall(r'\{([^}]+)\}',text)])
    expected=(len(axes['Hue'])+1)*len(axes['Sat'])*len(axes['Bri'])
    if rows.shape!=(expected,6) or not np.all(np.isfinite(rows)):raise ValueError('HSV 记录尺寸无效')
    ids=rows[:,:3]
    if np.any(ids!=np.floor(ids)) or len(set(map(tuple,ids)))!=expected:raise ValueError('HSV 节点重复/非整数')
    if np.any(ids<0) or np.any(ids>=(len(axes['Hue'])+1,len(axes['Sat']),len(axes['Bri']))):raise ValueError('HSV 节点索引越界')
    return dict(axes=axes,records=expected,value_min=rows[:,3:].min(axis=0).tolist(),
                value_max=rows[:,3:].max(axis=0).tolist(),interpretation='unverified; not imported')
