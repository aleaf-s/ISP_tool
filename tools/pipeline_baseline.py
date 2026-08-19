"""Create or verify deterministic RAW ISP Golden Output signatures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from isp_tool.validation import (
    build_pipeline_baseline,
    verify_pipeline_baseline,
)


DEFAULT_BASELINE = (
    PROJECT_ROOT / "examples" / "baselines" / "v0425_pipeline.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="baseline JSON path",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="replace the reference baseline instead of verifying it",
    )
    parser.add_argument("--width", type=int, default=160)
    parser.add_argument("--height", type=int, default=120)
    args = parser.parse_args()
    if args.width < 64 or args.height < 64:
        parser.error("width and height must both be >= 64")

    actual = build_pipeline_baseline(
        width=args.width, height=args.height
    )
    if args.write:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Golden baseline written: {args.baseline}")
        return 0
    if not args.baseline.exists():
        print(f"Golden baseline not found: {args.baseline}")
        return 2
    expected = json.loads(args.baseline.read_text(encoding="utf-8"))
    errors = verify_pipeline_baseline(expected, actual)
    if errors:
        print("Golden baseline verification failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(
        "Golden baseline verified: "
        f"{len(actual['cases'])} Bayer Pattern cases"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
