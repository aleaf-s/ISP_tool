"""Read-only audit of a 5508-word TXT and optional HSV companion."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from isp_tool.grading.hisi_clut import read_words,unpack_words,pack_deltas,inspect_hsv,addresses

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('txt');parser.add_argument('--hsv')
    args=parser.parse_args();words=read_words(args.txt);delta=unpack_words(words)
    coordinates,positions=addresses();padding=np.ones(5508,bool);padding[positions]=False
    groups=(coordinates[:,0]&1)+2*(coordinates[:,2]&1)+4*(coordinates[:,1]&1)
    report=dict(format_profile='CANN hi_isp_clut_lut 5508-word (not hardware colour certification)',
                bit_fields={'R':'9:0','G':'19:10','B':'29:20','reserved':'31:30 = 0'},
                signed_delta_range=[-511,511],grid_shape_rgb=[17,17,17],
                valid_nodes=len(positions),padding_slots=int(padding.sum()),
                padding_nonzero=int(np.count_nonzero(words[padding])),
                group_node_counts=np.bincount(groups,minlength=8).tolist(),
                valid_zero_nodes=int(np.count_nonzero(words[positions]==0)),
                words=len(words),roundtrip_equal=bool(np.array_equal(words,pack_deltas(delta))),
                sha256=hashlib.sha256(Path(args.txt).read_bytes()).hexdigest(),
                delta_min=delta.min(axis=(0,1,2)).tolist(),delta_max=delta.max(axis=(0,1,2)).tolist())
    if args.hsv:report['hsv']=inspect_hsv(args.hsv)
    print(json.dumps(report,ensure_ascii=False,indent=2))
