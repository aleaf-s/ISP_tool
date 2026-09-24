"""Read-only audit of a 5508-word TXT and optional HSV companion."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from isp_tool.grading.hisi_clut import read_words,unpack_words,pack_deltas,inspect_hsv

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('txt');parser.add_argument('--hsv')
    args=parser.parse_args();words=read_words(args.txt);delta=unpack_words(words)
    report=dict(words=len(words),roundtrip_equal=bool(np.array_equal(words,pack_deltas(delta))),
                sha256=hashlib.sha256(Path(args.txt).read_bytes()).hexdigest(),
                delta_min=delta.min(axis=(0,1,2)).tolist(),delta_max=delta.max(axis=(0,1,2)).tolist())
    if args.hsv:report['hsv']=inspect_hsv(args.hsv)
    print(json.dumps(report,ensure_ascii=False,indent=2))
