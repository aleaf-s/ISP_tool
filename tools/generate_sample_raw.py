#!/usr/bin/env python3
"""Generate a headerless uint16 little-endian Bayer sample and metadata JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from isp_tool.raw_io import synthetic_bayer


def main() -> None:
    output_dir = PROJECT_ROOT / "examples"
    output_dir.mkdir(exist_ok=True)
    sample = synthetic_bayer(3840, 2160, "RGGB")
    raw_path = output_dir / "synthetic_3840x2160_RGGB_12bit_u16le.raw"
    np.round(sample.image).astype("<u2").tofile(str(raw_path))
    metadata_path = output_dir / "synthetic_raw_metadata.json"
    metadata_path.write_text(
        json.dumps(sample.metadata.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(raw_path)
    print(metadata_path)


if __name__ == "__main__":
    main()

