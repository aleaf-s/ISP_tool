"""Device-specific log-Gain polyline approximation, not a vendor AWB model."""
from dataclasses import dataclass
import hashlib
import json
import numpy as np
from .awb_retune import MAX_GAIN, validate_ccm
from .ccm_encoding import decode_ccm, encode_ccm

OFF_TRACK_DISTANCE = .12  # Euclidean log-Gain heuristic, not hardware tolerance.
DEFAULT_FIXED = (
    (2300,1392,3804,((1606,7702,8100),(7830,1808,7770),(8021,7427,1960))),
    (3054,1728,3054,((1652,7768,7988),(7831,1803,7774),(8038,7557,1813))),
    (4166,2387,2524,((1734,7632,8042),(7899,1726,7783),(8088,7681,1639))),
    (5093,2667,2010,((1704,7635,8069),(7976,1688,7744),(8087,7707,1614))),
    (6500,3002,1703,((1767,7601,8040),(7976,1670,7762),(8152,7698,1558))),
)


def matrix_tuple(matrix):
    return tuple(tuple(float(v) for v in row) for row in matrix)


@dataclass(frozen=True)
class CalibrationPoint:
    cct: int
    r_gain: int
    b_gain: int
    ccm: tuple

    def __post_init__(self):
        if isinstance(self.cct,bool) or not isinstance(self.cct,int) or not 0<self.cct<=100000:
            raise ValueError('色温必须是 1～100000 K 的整数（软件范围）')
        for value in (self.r_gain,self.b_gain):
            if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=MAX_GAIN:
                raise ValueError(f'Gain 必须是 1～{MAX_GAIN} 的整数')
        object.__setattr__(self,'ccm',matrix_tuple(validate_ccm(self.ccm)))


@dataclass(frozen=True)
class LookupResult:
    ccm: tuple
    cct: float
    lower: int
    upper: int
    fraction: float
    distance: float
    limited: bool

    @property
    def warning(self):
        messages=[]
        if self.limited:messages.append('已限制在标定轨迹端点，不外推')
        if self.distance>OFF_TRACK_DISTANCE:messages.append('偏离标定轨迹，CCM 为近似估计')
        return '；'.join(messages)


@dataclass(frozen=True)
class CalibrationTable:
    points: tuple
    name: str = '用户设备五点标定'

    def __post_init__(self):
        if not isinstance(self.name,str) or not self.name.strip():raise ValueError('配置名称不能为空')
        if not 2<=len(self.points)<=128:raise ValueError('标定表需要 2～128 个有效标定点')
        points=tuple(sorted(self.points,key=lambda p:p.cct))
        if len({p.cct for p in points})!=len(points):raise ValueError('色温标定点重复')
        if len({(p.r_gain,p.b_gain) for p in points})!=len(points):raise ValueError('Gain 标定点重复')
        object.__setattr__(self,'points',points)

    @classmethod
    def default(cls):
        return cls(tuple(CalibrationPoint(c,r,b,tuple(tuple(decode_ccm(v) for v in row) for row in m)) for c,r,b,m in DEFAULT_FIXED))

    def lookup(self,r_gain,b_gain):
        gain=np.asarray([r_gain,b_gain],np.float64)
        if not np.all(np.isfinite(gain)) or np.any(gain<=0) or np.any(gain>MAX_GAIN):raise ValueError('待估算 Gain 超出有效范围')
        for p in self.points:
            if r_gain==p.r_gain and b_gain==p.b_gain:
                return LookupResult(p.ccm,float(p.cct),p.cct,p.cct,0.,0.,False)
        coords=np.log(np.array([(p.r_gain,p.b_gain) for p in self.points],np.float64)/1024)
        point=np.log(gain/1024)
        best=None
        for index,(a,b) in enumerate(zip(coords[:-1],coords[1:])):
            delta=b-a
            raw=float(np.dot(point-a,delta)/np.dot(delta,delta))
            t=float(np.clip(raw,0,1))
            distance=float(np.linalg.norm(point-(a+t*delta)))
            if best is None or distance<best[0]:best=(distance,index,t,raw)
        distance,index,t,raw=best
        p0,p1=self.points[index:index+2]
        matrix=(1-t)*np.asarray(p0.ccm)+t*np.asarray(p1.ccm)
        validate_ccm(matrix)  # Well-conditioned endpoints need not imply a safe interior.
        cct=1/((1-t)/p0.cct+t/p1.cct)
        limited=(index==0 and raw<0) or (index==len(self.points)-2 and raw>1)
        return LookupResult(matrix_tuple(matrix),cct,p0.cct,p1.cct,t,distance,limited)

    def to_payload(self,encoding='float'):
        if encoding not in ('float','fixed13'):raise ValueError('未知 CCM 编码')
        points=[]
        for p in self.points:
            matrix=p.ccm if encoding=='float' else [[encode_ccm(v) for v in row] for row in p.ccm]
            points.append(dict(cct=p.cct,r_gain=p.r_gain,b_gain=p.b_gain,ccm=matrix))
        return dict(schema='awb_ccm_calibration',version=1,name=self.name,gain_scale=1024,
                    ccm_encoding=encoding,ccm_scale=1 if encoding=='float' else 1024,points=points)

    @classmethod
    def from_payload(cls,payload):
        if not isinstance(payload,dict):raise ValueError('标定文件必须是 JSON 对象')
        if payload.get('schema')!='awb_ccm_calibration' or payload.get('version')!=1 or payload.get('gain_scale')!=1024:
            raise ValueError('不支持的标定版本或 Gain 缩放')
        encoding=payload.get('ccm_encoding')
        if encoding not in ('float','fixed13') or payload.get('ccm_scale')!=(1 if encoding=='float' else 1024):
            raise ValueError('CCM 编码或缩放缺失/不匹配')
        points=payload.get('points')
        if not isinstance(points,list) or not 2<=len(points)<=128:raise ValueError('标定点数量无效')
        parsed=[]
        try:
            for p in points:
                matrix=p['ccm']
                if np.shape(matrix)!=(3,3):raise ValueError('CCM 必须是 3×3')
                if encoding=='fixed13':
                    if any(isinstance(v,bool) or not isinstance(v,int) for row in matrix for v in row):raise ValueError('Fixed CCM 必须是整数编码')
                    matrix=[[decode_ccm(v) for v in row] for row in matrix]
                else:
                    if any(isinstance(v,bool) or not isinstance(v,(int,float)) for row in matrix for v in row):raise ValueError('Float CCM 必须是实际数值')
                parsed.append(CalibrationPoint(p['cct'],p['r_gain'],p['b_gain'],matrix))
            return cls(tuple(parsed),payload['name'])
        except (KeyError,TypeError) as exc:raise ValueError('标定文件字段不完整') from exc

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.to_payload(),sort_keys=True).encode()).hexdigest()
