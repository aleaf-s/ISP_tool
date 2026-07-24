from __future__ import annotations

import csv
import json
from pathlib import Path

from .. import __version__
from ..models import CalibrationSession, ISPError


def export_calibration_report(path: str, session: CalibrationSession) -> None:
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix == ".json":
        payload = {
            "tool": "ISP RAW Visual Simulator",
            "tool_version": __version__,
            "calibration": session.to_dict(),
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return
    if suffix == ".csv":
        with target.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["section", "item", "value"])
            writer.writerow(["session", "name", session.name])
            writer.writerow(["session", "sensor", session.sensor_name])
            writer.writerow(["session", "illuminant", session.illuminant])
            if session.awb_result:
                for name, value in session.awb_result.gains().items():
                    writer.writerow(["AWB", f"{name} Gain", value])
                writer.writerow(["AWB", "confidence", session.awb_result.confidence])
            if session.ae_result:
                writer.writerow(["AE", "suggested_gain", session.ae_result.suggested_gain])
                writer.writerow(["AE", "predicted_clipping", session.ae_result.predicted_clipped_ratio])
            if session.ccm_result:
                for row, values in enumerate(session.ccm_result.matrix):
                    writer.writerow(["CCM", f"row_{row}", " ".join(map(str, values))])
                writer.writerow(["CCM", "offset", " ".join(map(str, session.ccm_result.offset))])
                for patch in session.ccm_result.patches:
                    writer.writerow([
                        "Patch", patch.patch_id,
                        json.dumps({
                            "name": patch.name,
                            "measured_rgb": patch.measured_rgb.tolist(),
                            "reference_rgb": patch.reference_rgb.tolist(),
                            "delta_e": patch.delta_e,
                        }, ensure_ascii=False),
                    ])
            for module_id, result in session.auto_recommendations.items():
                writer.writerow([
                    "Auto Analysis", f"{module_id}.confidence",
                    result.confidence,
                ])
                writer.writerow([
                    "Auto Analysis", f"{module_id}.method", result.method,
                ])
                for key, value in result.suggested_parameters.items():
                    writer.writerow([
                        "Auto Analysis",
                        f"{module_id}.suggested.{key}",
                        value,
                    ])
                for warning in result.warnings:
                    writer.writerow([
                        "Auto Analysis", f"{module_id}.warning", warning,
                    ])
        return
    if suffix in {".md", ".markdown"}:
        lines = [
            "# ISP Calibration Report",
            "",
            f"- Tool version: {__version__}",
            f"- Session: {session.name or 'Untitled'}",
            f"- Sensor: {session.sensor_name or 'Unknown'}",
            f"- Illuminant: {session.illuminant}",
            f"- RAW: {session.raw_metadata.width}×{session.raw_metadata.height}, "
            f"{session.raw_metadata.bit_depth}-bit, {session.raw_metadata.bayer_pattern}",
            "",
        ]
        if session.lsc_mesh:
            lines.extend([
                "## LSC Mesh", "",
                f"- Size: {session.lsc_mesh.rows}×{session.lsc_mesh.cols}",
                f"- Source: {session.lsc_mesh.source}",
                "",
            ])
        if session.awb_result:
            result = session.awb_result
            lines.extend([
                "## AWB", "",
                f"- Method: {result.method}",
                f"- Gains: R {result.r_gain:.6f}, Gr {result.gr_gain:.6f}, "
                f"Gb {result.gb_gain:.6f}, B {result.b_gain:.6f}",
                f"- Confidence: {result.confidence:.3f}",
                "",
            ])
        if session.ae_result:
            result = session.ae_result
            lines.extend([
                "## AE", "",
                f"- Method: {result.method}",
                f"- Suggested gain: {result.suggested_gain:.6f}",
                f"- Predicted clipping: {result.predicted_clipped_ratio:.4%}",
                "",
            ])
        if session.ccm_result:
            result = session.ccm_result
            lines.extend([
                "## ColorChecker / CCM", "",
                f"- Method: {result.method}",
                f"- Condition number: {result.condition_number:.5g}",
                f"- ΔE00 before mean: {result.delta_e_before.get('mean', 0):.4f}",
                f"- ΔE00 after mean: {result.delta_e_after.get('mean', 0):.4f}",
                f"- ΔE00 after max: {result.delta_e_after.get('max', 0):.4f}",
                f"- ΔE00 after P90: {result.delta_e_after.get('p90', 0):.4f}",
                f"- ΔE76 before mean: "
                f"{result.diagnostics.get('delta_e76_before', {}).get('mean', 0):.4f}",
                f"- ΔE76 after mean: "
                f"{result.diagnostics.get('delta_e76_after', {}).get('mean', 0):.4f}",
                "",
                "```text",
            ])
            lines.extend(" ".join(f"{value:.9g}" for value in row) for row in result.matrix)
            lines.extend(["```", ""])
        if session.auto_recommendations:
            lines.extend(["## Automatic Analysis", ""])
            for module_id, result in session.auto_recommendations.items():
                lines.extend([
                    f"### {module_id}",
                    "",
                    f"- Target: `{result.target}`",
                    f"- Method: {result.method or 'Default'}",
                    f"- Confidence: {result.confidence:.1%}",
                    f"- Source: {result.source_description or 'Current image'}",
                    f"- Status: {'Applied' if result.applied else 'Suggested'}",
                    f"- Elapsed: {result.elapsed_ms:.2f} ms",
                    "- Suggested parameters:",
                ])
                lines.extend(
                    f"  - `{key}`: {value}"
                    for key, value in result.suggested_parameters.items()
                )
                if result.warnings:
                    lines.append("- Warnings:")
                    lines.extend(f"  - {warning}" for warning in result.warnings)
                lines.append("")
        if session.noise_profile:
            lines.extend([
                "## Noise Profile",
                "",
                "```json",
                json.dumps(session.noise_profile, ensure_ascii=False, indent=2),
                "```",
                "",
            ])
        if session.calibration_history:
            lines.extend([
                "## Calibration History",
                "",
                f"- Applied recommendation count: {len(session.calibration_history)}",
                "",
            ])
        if session.notes:
            lines.extend(["## Notes", "", session.notes, ""])
        target.write_text("\n".join(lines), encoding="utf-8")
        return
    raise ISPError(f"不支持的校准报告格式：{suffix}")
