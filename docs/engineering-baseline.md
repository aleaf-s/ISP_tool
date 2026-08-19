# Engineering Baseline

This document defines the regression contract used before structural changes.

## Active product surface

- RAW ISP: `RAW Input → BLC → LSC → WB → Demosaic → CCM`.
- YUV preview: `YUV Input → Chroma Upsampling → YUV to RGB → Display Preview`.
- Shared tools: ROI, Compare, Histogram, Waveform, Vectorscope, Statistics,
  Pixel Inspector, Line Profile, final-impact preview, multi-image workset and
  bilingual UI.
- Optional compute backend: Auto, OpenCV/NumPy and compatible Native C++.

The inactive DPC, Tone, NR, Sharpen and Color Adjustment implementations are
compatibility code. They are not part of the active UI regression contract.

## Algorithm contract

The committed reference file is
`examples/baselines/v0425_pipeline.json`. It uses a deterministic 160×120
synthetic RAW image for RGGB, GRBG, GBRG and BGGR. Every active RAW stage stores:

- domain, encoding and normalized state;
- output shape;
- min/max/mean/stddev and percentiles for diagnostics;
- SHA-256 of a sensor-relevant 12-bit quantized image.

Verify the current implementation:

```powershell
python tools\pipeline_baseline.py
```

Only replace the reference after an intentional algorithm change has been
reviewed visually and numerically:

```powershell
python tools\pipeline_baseline.py --write
```

## Local performance baseline

Performance is machine-specific and is therefore written below the ignored
`.artifacts/` directory:

```powershell
python tools\benchmark_pipeline.py `
  --backend opencv `
  --iterations 7 `
  --json-out .artifacts\performance\local_baseline.json
```

Compare cold pipeline time, cached CCM edit time and module medians on the same
machine. Timing changes must not be judged across different CPU, Python,
OpenCV or backend configurations.

## Architecture boundaries

- `isp_tool/modules` and `isp_tool/pipeline.py` must not import UI code.
- Controllers under `isp_tool/ui/controllers` may construct application
  payloads but must not build widget layouts.
- Display encoding must not mutate pipeline data or calibration samples.
- A disabled module preserves pixels and `StageDataState` exactly.
- Background work must be cancellable or superseded; stale results must never
  replace the current image.

## Current technical-debt register

| Area | Current state | Planned action |
|---|---|---|
| Main window | `app.py` still owns most UI orchestration | Extract one tested controller per iteration |
| YUV preview | Pure conversion previously lived in `app.py` | Extracted in V0.4.26 |
| Language state | Preference logic previously lived in `app.py` | Extracted in V0.4.26 |
| Preview jobs | Request lifecycle extracted in V0.4.27; result decision extracted in V0.4.33 | Keep Tk scheduling and widget mutation in `app.py` |
| Preview result | Future decision and payload validation extracted in V0.4.33; UI assignment remains in `app.py` | Keep widget mutation at the UI boundary |
| Workspace cache | Validity, LRU and byte-budget policy extracted in V0.4.31 | Keep UI counters at the application boundary |
| Work-item state | Editable snapshot/store/activation boundary extracted in V0.4.32 | Keep widget refresh and job submission in `app.py` |
| ROI interaction | Gesture arbitration and pointer lifecycle extracted in V0.4.30; ROI geometry mutation remains in `app.py` | Keep geometry local until ROI editing is redesigned |
| Legacy calibration UI | Retained for compatibility but mostly hidden | Do not expose without a concrete workflow requirement |
| UI framework | Tk remains adequate for the current scope | Reassess PySide6/OpenGL only after profiling |

## Next structural slice

The next structural slice is performance-result accounting. It should move
module timing aggregation, shared-array memory estimation and cache ratio
formatting out of `app.py`, while leaving visible status text and widgets at the
UI boundary.
