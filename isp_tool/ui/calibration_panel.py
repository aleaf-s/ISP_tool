from __future__ import annotations

import copy
import json
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable, Optional

import numpy as np

from ..calibration.ae import estimate_exposure
from ..calibration.awb import estimate_awb
from ..calibration.ccm_solver import solve_ccm_from_patches
from ..calibration.colorchecker import (
    colorchecker_reference,
    generate_colorchecker_grid,
    reorder_reference_indices,
    sample_colorchecker,
)
from ..calibration.flat_field import generate_lsc_mesh
from ..calibration.lsc_mesh import load_lsc_mesh, save_lsc_mesh
from ..calibration.report import export_calibration_report
from ..models import CalibrationSession, ImageROI, ISPError, LSCMesh
from .auto_calibration_panel import AutoCalibrationPanel
from .colorchecker_editor import ColorCheckerCornerEditor
from .lsc_mesh_editor import LSCMeshEditor
from .theme import COLORS, FONTS


class CalibrationWorkspace(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("快速自动矫正 · V0.4.15")
        self.geometry("720x700")
        self.minsize(620, 560)
        self.transient(parent)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="isp-calibration")
        self.current_future: Optional[Future] = None
        self.generation = 0
        self.pending_mesh: Optional[LSCMesh] = None
        self.previous_lsc = None
        self.previous_awb = None
        self.previous_ae = None
        self.previous_ccm = None
        self.calibration_polygons = []
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)

    @property
    def session(self) -> CalibrationSession:
        return self.app.calibration_session

    def _build(self):
        self.status_var = tk.StringVar(value="Ready")
        self._init_shared_calibration_state()
        self.session_name_var = tk.StringVar(value=self.session.name)
        self.sensor_name_var = tk.StringVar(value=self.session.sensor_name)
        self.illuminant_var = tk.StringVar(value=self.session.illuminant)
        self.notes_var = tk.StringVar(value=self.session.notes)
        self.auto_tab = ttk.Frame(self, padding=(8, 0, 8, 8))
        self.auto_tab.pack(fill="both", expand=True)
        self.auto_panel = AutoCalibrationPanel(
            self.auto_tab, self, self.app
        )
        self.auto_panel.pack(fill="both", expand=True)
        self.load_ui_state(
            getattr(self.app, "loaded_ui_state", {}).get("calibration", {})
        )

    def _init_shared_calibration_state(self) -> None:
        self.mesh_rows_var = tk.IntVar(value=13)
        self.mesh_cols_var = tk.IntVar(value=17)
        self.mesh_stat_var = tk.StringVar(value="Median")
        self.awb_method_var = tk.StringVar(value="Robust Neutral")
        self.awb_use_roi_var = tk.BooleanVar(value=True)
        self.ae_method_var = tk.StringVar(
            value="Highlight Protected"
        )
        self.ae_target_var = tk.DoubleVar(value=0.45)
        self.ae_use_roi_var = tk.BooleanVar(value=False)
        self.corner_vars = [
            tk.StringVar(value=value)
            for value in (
                "20,20", "620,20", "620,420", "20,420"
            )
        ]
        self.ccm_rotation_var = tk.IntVar(value=0)
        self.ccm_flip_var = tk.BooleanVar(value=False)
        self.ccm_offset_var = tk.BooleanVar(value=True)
        self.ccm_ridge_var = tk.DoubleVar(value=0.0001)
        self.ccm_exclude_var = tk.StringVar(value="")

    def _result_area(self, parent):
        text = ScrolledText(
            parent, height=18, bg=COLORS["background"],
            fg=COLORS["foreground"],
            insertbackground="white", font=FONTS["mono"],
        )
        text.pack(fill="both", expand=True, pady=(10, 0))
        return text

    def _build_lsc(self):
        controls = ttk.Frame(self.lsc_tab)
        controls.pack(fill="x")
        self.mesh_rows_var = tk.IntVar(value=13)
        self.mesh_cols_var = tk.IntVar(value=17)
        self.mesh_stat_var = tk.StringVar(value="Median")
        for label, variable, values in (
            ("Rows", self.mesh_rows_var, (7, 9, 13, 25)),
            ("Cols", self.mesh_cols_var, (9, 13, 17, 33)),
            ("Statistic", self.mesh_stat_var, ("Median", "Trimmed Mean")),
        ):
            ttk.Label(controls, text=label).pack(side="left", padx=(0, 4))
            ttk.Combobox(
                controls, textvariable=variable, values=values,
                width=10,
                state="normal" if label in {"Rows", "Cols"} else "readonly",
            ).pack(side="left", padx=(0, 10))
        ttk.Button(
            controls, text="Generate from current BLC", command=self._generate_mesh
        ).pack(side="left")
        ttk.Button(controls, text="Import", command=self._import_mesh).pack(side="left", padx=4)
        ttk.Button(controls, text="Export", command=self._export_mesh).pack(side="left")
        actions = ttk.Frame(self.lsc_tab)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Edit Mesh", command=self._edit_mesh).pack(side="left")
        ttk.Button(actions, text="Preview", command=self._preview_mesh).pack(side="left", padx=4)
        ttk.Button(actions, text="Apply", command=self._apply_mesh).pack(side="left")
        ttk.Button(actions, text="Revert", command=self._revert_mesh).pack(side="left", padx=4)
        self.lsc_state = ttk.Label(actions, text="Not Calculated", style="Muted.TLabel")
        self.lsc_state.pack(side="right")
        self.lsc_result = self._result_area(self.lsc_tab)

    def _build_awb(self):
        controls = ttk.Frame(self.awb_tab)
        controls.pack(fill="x")
        self.awb_method_var = tk.StringVar(value="Robust Neutral")
        ttk.Label(controls, text="Method").pack(side="left")
        ttk.Combobox(
            controls, textvariable=self.awb_method_var,
            values=(
                "Robust Neutral",
                "ROI Neutral",
                "Gray World",
                "Shades of Gray",
                "White Patch",
            ),
            state="readonly", width=18,
        ).pack(side="left", padx=6)
        self.awb_use_roi_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            controls, text="Use current ROI", variable=self.awb_use_roi_var
        ).pack(side="left")
        ttk.Button(controls, text="Calculate", command=self._calculate_awb).pack(side="left", padx=8)
        ttk.Button(controls, text="Preview", command=self._preview_awb).pack(side="left")
        ttk.Button(controls, text="Apply", command=self._apply_awb).pack(side="left", padx=4)
        ttk.Button(controls, text="Revert", command=self._revert_awb).pack(side="left")
        self.awb_state = ttk.Label(controls, text="Not Calculated", style="Muted.TLabel")
        self.awb_state.pack(side="right")
        self.awb_result_text = self._result_area(self.awb_tab)

    def _build_ae(self):
        controls = ttk.Frame(self.ae_tab)
        controls.pack(fill="x")
        self.ae_method_var = tk.StringVar(value="Highlight Protected")
        self.ae_target_var = tk.DoubleVar(value=0.45)
        ttk.Label(controls, text="Method").pack(side="left")
        ttk.Combobox(
            controls, textvariable=self.ae_method_var,
            values=("Mean Luma", "Median Luma", "Percentile", "Highlight Protected"),
            state="readonly", width=19,
        ).pack(side="left", padx=6)
        ttk.Label(controls, text="Target").pack(side="left")
        ttk.Entry(controls, textvariable=self.ae_target_var, width=7).pack(side="left", padx=5)
        self.ae_use_roi_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls, text="Use current ROI", variable=self.ae_use_roi_var
        ).pack(side="left")
        ttk.Button(controls, text="Calculate", command=self._calculate_ae).pack(side="left", padx=8)
        ttk.Button(controls, text="Preview", command=self._preview_ae).pack(side="left")
        ttk.Button(controls, text="Apply", command=self._apply_ae).pack(side="left", padx=4)
        ttk.Button(controls, text="Revert", command=self._revert_ae).pack(side="left")
        self.ae_state = ttk.Label(controls, text="Not Calculated", style="Muted.TLabel")
        self.ae_state.pack(side="right")
        self.ae_result_text = self._result_area(self.ae_tab)

    def _build_ccm(self):
        corner_frame = ttk.Frame(self.ccm_tab)
        corner_frame.pack(fill="x")
        self.corner_vars = [
            tk.StringVar(value=value)
            for value in ("20,20", "620,20", "620,420", "20,420")
        ]
        for label, variable in zip(("TL", "TR", "BR", "BL"), self.corner_vars):
            ttk.Label(corner_frame, text=label).pack(side="left")
            ttk.Entry(corner_frame, textvariable=variable, width=12).pack(side="left", padx=(3, 8))
        ttk.Button(
            corner_frame, text="Use current ROI", command=self._corners_from_roi
        ).pack(side="left")
        ttk.Button(
            corner_frame, text="Edit corners", command=self._edit_colorchecker_corners
        ).pack(side="left", padx=4)
        options = ttk.Frame(self.ccm_tab)
        options.pack(fill="x", pady=(8, 0))
        self.ccm_rotation_var = tk.IntVar(value=0)
        self.ccm_flip_var = tk.BooleanVar(value=False)
        self.ccm_offset_var = tk.BooleanVar(value=True)
        self.ccm_ridge_var = tk.DoubleVar(value=0.0001)
        self.ccm_exclude_var = tk.StringVar(value="")
        ttk.Label(options, text="Rotation").pack(side="left")
        ttk.Combobox(
            options, textvariable=self.ccm_rotation_var,
            values=(0, 90, 180, 270), state="readonly", width=6,
        ).pack(side="left", padx=4)
        ttk.Checkbutton(options, text="Flip", variable=self.ccm_flip_var).pack(side="left")
        ttk.Checkbutton(options, text="Offset", variable=self.ccm_offset_var).pack(side="left")
        ttk.Label(options, text="Ridge").pack(side="left", padx=(8, 3))
        ttk.Entry(options, textvariable=self.ccm_ridge_var, width=9).pack(side="left")
        ttk.Label(options, text="Exclude").pack(side="left", padx=(8, 3))
        ttk.Entry(options, textvariable=self.ccm_exclude_var, width=9).pack(side="left")
        ttk.Button(
            options, text="Calculate CCM", command=self._calculate_ccm
        ).pack(side="left", padx=8)
        ttk.Button(options, text="Preview", command=self._preview_ccm).pack(side="left")
        ttk.Button(options, text="Apply", command=self._apply_ccm).pack(side="left", padx=4)
        ttk.Button(options, text="Revert", command=self._revert_ccm).pack(side="left")
        self.ccm_state = ttk.Label(options, text="Not Calculated", style="Muted.TLabel")
        self.ccm_state.pack(side="right")
        self.ccm_result_text = self._result_area(self.ccm_tab)

    def _run_async(self, label: str, task: Callable, callback: Callable):
        self.generation += 1
        generation = self.generation
        self.status_var.set(f"{label}…")
        if self.current_future is not None and not self.current_future.done():
            self.current_future.cancel()
        future = self.executor.submit(task)
        self.current_future = future

        def poll():
            if not future.done():
                if self.winfo_exists():
                    self.after(20, poll)
                return
            if generation != self.generation or not self.winfo_exists():
                return
            try:
                result = future.result()
            except Exception as exc:
                self.status_var.set("Failed")
                messagebox.showerror(f"{label} 失败", str(exc), parent=self)
                return
            self.status_var.set("Ready")
            callback(result)

        self.after(20, poll)

    def _full_stage(self, index: int):
        if not self.app.results:
            raise ISPError("请等待 ISP 预览处理完成")
        if self.app.roi_process_var.get():
            raise ISPError("校准前请关闭 Process ROI，以使用完整预览坐标")
        return self.app.results[index]

    def _roi(self, enabled: bool):
        return self.app.roi if enabled else None

    def _generate_mesh(self):
        try:
            stage = self._full_stage(1)
            image = stage.image.copy()
            metadata = copy.deepcopy(self.app.loaded.metadata)
            rows, cols = self.mesh_rows_var.get(), self.mesh_cols_var.get()
            statistic = self.mesh_stat_var.get()
            gain_limit = float(
                self.app.pipeline.module_by_id(
                    "lens_shading_correction"
                ).parameters["max_gain"]
            )
        except Exception as exc:
            messagebox.showerror("LSC Mesh", str(exc), parent=self)
            return
        self._run_async(
            "Generate LSC Mesh",
            lambda: generate_lsc_mesh(
                image, metadata, rows, cols,
                statistic=statistic, gain_limit=gain_limit,
            ),
            self._mesh_generated,
        )

    def _mesh_generated(self, result):
        mesh, diagnostics, _artifacts = result
        self.pending_mesh = mesh
        self.lsc_state.configure(text="Calculated")
        self._set_text(
            self.lsc_result,
            json.dumps({
                "mesh": f"{mesh.rows}×{mesh.cols}",
                **diagnostics,
            }, ensure_ascii=False, indent=2),
        )

    def _import_mesh(self):
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("LSC Mesh", "*.json *.csv *.npz *.npy"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            self.pending_mesh = load_lsc_mesh(path)
            self.pending_mesh.validate(float(
                self.app.pipeline.module_by_id(
                    "lens_shading_correction"
                ).parameters["max_gain"]
            ))
        except Exception as exc:
            messagebox.showerror("导入 Mesh 失败", str(exc), parent=self)
            return
        self.lsc_state.configure(text="Calculated")
        self._set_text(
            self.lsc_result,
            f"Loaded: {path}\nSize: {self.pending_mesh.rows}×{self.pending_mesh.cols}",
        )

    def _export_mesh(self):
        mesh = self.pending_mesh or self.session.lsc_mesh
        if mesh is None:
            messagebox.showinfo("LSC Mesh", "尚无可导出的 Mesh。", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("CSV", "*.csv"), ("NPZ", "*.npz"), ("NPY", "*.npy")],
        )
        if path:
            try:
                save_lsc_mesh(path, mesh)
            except Exception as exc:
                messagebox.showerror("导出 Mesh 失败", str(exc), parent=self)

    def _edit_mesh(self):
        mesh = self.pending_mesh or self.session.lsc_mesh
        if mesh is None:
            messagebox.showinfo("LSC Mesh", "请先生成或导入 Mesh。", parent=self)
            return
        LSCMeshEditor(self, mesh, self._mesh_edited)

    def _mesh_edited(self, mesh):
        mesh.validate(float(
            self.app.pipeline.module_by_id(
                "lens_shading_correction"
            ).parameters["max_gain"]
        ))
        self.pending_mesh = mesh
        self.lsc_state.configure(text="Calculated")

    def _preview_mesh(self):
        if self.pending_mesh is None:
            messagebox.showinfo("LSC Mesh", "请先生成或导入 Mesh。", parent=self)
            return
        module = self.app.pipeline.module_by_id("lens_shading_correction")
        if self.previous_lsc is None:
            self.previous_lsc = (module.mesh.copy() if module.mesh else None, dict(module.parameters))
        module.set_mesh(self.pending_mesh)
        module.parameters["mode"] = "Mesh Model"
        self.lsc_state.configure(text="Previewed")
        self.app.schedule_process(immediate=True)

    def _apply_mesh(self):
        if self.pending_mesh is None:
            messagebox.showinfo("LSC Mesh", "请先生成或导入 Mesh。", parent=self)
            return
        self._preview_mesh()
        self.session.lsc_mesh = self.pending_mesh.copy()
        self.previous_lsc = None
        self.lsc_state.configure(text="Applied")

    def _revert_mesh(self):
        if self.previous_lsc is None:
            return
        module = self.app.pipeline.module_by_id("lens_shading_correction")
        mesh, parameters = self.previous_lsc
        module.set_mesh(mesh)
        module.parameters = parameters
        self.previous_lsc = None
        self.lsc_state.configure(text="Calculated")
        self.app.schedule_process(immediate=True)

    def _calculate_awb(self):
        try:
            stage = self._full_stage(3)
            image, metadata = stage.image.copy(), copy.deepcopy(self.app.loaded.metadata)
            method = self.awb_method_var.get()
            roi = self._roi(self.awb_use_roi_var.get())
        except Exception as exc:
            messagebox.showerror("AWB", str(exc), parent=self)
            return
        self._run_async(
            "Calculate AWB",
            lambda: estimate_awb(image, metadata, method=method, roi=roi),
            self._awb_calculated,
        )

    def _awb_calculated(self, result):
        self.session.awb_result = result
        self.awb_state.configure(text="Calculated")
        self._set_text(self.awb_result_text, json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

    def _preview_awb(self):
        result = self.session.awb_result
        if result is None:
            return
        module = self.app.pipeline.module_by_id("white_balance")
        if self.previous_awb is None:
            self.previous_awb = dict(module.parameters)
        module.parameters.update({
            "r_gain": result.r_gain, "gr_gain": result.gr_gain,
            "gb_gain": result.gb_gain, "b_gain": result.b_gain,
        })
        self.awb_state.configure(text="Previewed")
        self.app.schedule_process(immediate=True)

    def _apply_awb(self):
        if self.session.awb_result is None:
            return
        self._preview_awb()
        self.previous_awb = None
        self.awb_state.configure(text="Applied")

    def _revert_awb(self):
        if self.previous_awb is None:
            return
        self.app.pipeline.module_by_id("white_balance").parameters = self.previous_awb
        self.previous_awb = None
        self.awb_state.configure(text="Calculated")
        self.app.schedule_process(immediate=True)

    def _calculate_ae(self):
        try:
            stage = self._full_stage(3)
            image, domain = stage.image.copy(), stage.domain
            metadata = copy.deepcopy(self.app.loaded.metadata)
            method, target = self.ae_method_var.get(), float(self.ae_target_var.get())
            roi = self._roi(self.ae_use_roi_var.get())
        except Exception as exc:
            messagebox.showerror("AE", str(exc), parent=self)
            return
        self._run_async(
            "Calculate AE",
            lambda: estimate_exposure(
                image, domain, metadata, method=method,
                target_level=target, roi=roi,
            ),
            self._ae_calculated,
        )

    def _ae_calculated(self, result):
        self.session.ae_result = result
        self.ae_state.configure(text="Calculated")
        self._set_text(self.ae_result_text, json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

    def _preview_ae(self):
        result = self.session.ae_result
        if result is None:
            return
        module = self.app.pipeline.module_by_id("white_balance")
        if self.previous_ae is None:
            self.previous_ae = float(module.parameters["exposure_gain"])
        module.parameters["exposure_gain"] = result.suggested_gain
        self.ae_state.configure(text="Previewed")
        self.app.schedule_process(immediate=True)

    def _apply_ae(self):
        if self.session.ae_result is None:
            return
        self._preview_ae()
        self.previous_ae = None
        self.ae_state.configure(text="Applied")

    def _revert_ae(self):
        if self.previous_ae is None:
            return
        self.app.pipeline.module_by_id("white_balance").parameters["exposure_gain"] = self.previous_ae
        self.previous_ae = None
        self.ae_state.configure(text="Calculated")
        self.app.schedule_process(immediate=True)

    def _corners_from_roi(self):
        roi = self.app.roi
        if roi is None:
            messagebox.showinfo("ColorChecker", "请先在主界面框选色卡外框。", parent=self)
            return
        points = ((roi.x, roi.y), (roi.x2, roi.y), (roi.x2, roi.y2), (roi.x, roi.y2))
        for variable, point in zip(self.corner_vars, points):
            variable.set(f"{point[0]},{point[1]}")

    def _parse_corners(self):
        corners = []
        for variable in self.corner_vars:
            tokens = variable.get().replace("，", ",").split(",")
            if len(tokens) != 2:
                raise ISPError("角点格式应为 x,y")
            corners.append((float(tokens[0]), float(tokens[1])))
        return corners

    def _edit_colorchecker_corners(self):
        try:
            stage = self._full_stage(5)
            if stage.domain != "rgb":
                raise ISPError("ColorChecker 角点编辑需要线性 RGB")
            corners = self._parse_corners()
        except Exception as exc:
            messagebox.showerror("ColorChecker", str(exc), parent=self)
            return
        ColorCheckerCornerEditor(
            self,
            stage.image,
            corners,
            int(self.ccm_rotation_var.get()),
            self._set_colorchecker_corners,
        )

    def _set_colorchecker_corners(self, corners):
        for variable, point in zip(self.corner_vars, corners):
            variable.set(f"{point[0]:.3f},{point[1]:.3f}")

    def _calculate_ccm(self):
        try:
            stage = self._full_stage(5)
            if stage.domain != "rgb":
                raise ISPError("ColorChecker 校准输入不是 Demosaic 后的线性 RGB")
            image = stage.image.copy()
            corners = self._parse_corners()
            rotation = int(self.ccm_rotation_var.get())
            flipped = bool(self.ccm_flip_var.get())
            include_offset = bool(self.ccm_offset_var.get())
            ridge = float(self.ccm_ridge_var.get())
            excluded = {
                int(token)
                for token in self.ccm_exclude_var.get().replace("，", ",").split(",")
                if token.strip()
            }
            if any(index < 1 or index > 24 for index in excluded):
                raise ISPError("Exclude 色块编号必须在 1～24")
        except Exception as exc:
            messagebox.showerror("ColorChecker", str(exc), parent=self)
            return

        def task():
            columns, rows = ((4, 6) if rotation in {90, 270} else (6, 4))
            polygons = generate_colorchecker_grid(
                corners, columns=columns, rows=rows
            )
            names, references = colorchecker_reference(
                illuminant=self.illuminant_var.get()
            )
            order = reorder_reference_indices(rotation, flipped)
            patches = sample_colorchecker(
                image, polygons, references, names, reference_indices=order
            )
            patches = [patch for patch in patches if patch.patch_id not in excluded]
            weights = np.array([
                2.0 if patch.patch_id >= 19 else (
                    1.5 if patch.patch_id in {1, 2} else 1.0
                )
                for patch in patches
            ], np.float64)
            result = solve_ccm_from_patches(
                patches, include_offset=include_offset,
                ridge=ridge, weights=weights, white_constraint=True,
            )
            return result, polygons

        self._run_async("ColorChecker CCM", task, self._ccm_calculated)

    def _ccm_calculated(self, payload):
        result, polygons = payload
        self.session.ccm_result = result
        self.app.calibration_polygons = polygons
        self.app.render_current()
        if result.condition_number > 1e5:
            self.ccm_state.configure(
                text="Calculated · ill-conditioned",
                foreground=COLORS["error"],
            )
        else:
            self.ccm_state.configure(
                text="Calculated", foreground=COLORS["muted"]
            )
        summary = {
            "method": result.method,
            "condition_number": result.condition_number,
            "matrix": result.matrix.tolist(),
            "offset": result.offset.tolist(),
            "delta_e_before": result.delta_e_before,
            "delta_e_after": result.delta_e_after,
            "delta_e76_before": result.diagnostics.get("delta_e76_before"),
            "delta_e76_after": result.diagnostics.get("delta_e76_after"),
            "worst_5": [
                {"id": patch.patch_id, "name": patch.name, "delta_e": patch.delta_e}
                for patch in sorted(result.patches, key=lambda item: item.delta_e, reverse=True)[:5]
            ],
        }
        self._set_text(self.ccm_result_text, json.dumps(summary, ensure_ascii=False, indent=2))

    def _preview_ccm(self):
        result = self.session.ccm_result
        if result is None:
            return
        module = self.app.pipeline.module_by_id("color_correction_matrix")
        if self.previous_ccm is None:
            self.previous_ccm = dict(module.parameters)
        for row in range(3):
            for col in range(3):
                module.parameters[f"m{row}{col}"] = float(result.matrix[row, col])
        module.parameters.update({
            "offset_r": float(result.offset[0]),
            "offset_g": float(result.offset[1]),
            "offset_b": float(result.offset[2]),
            "strength": 1.0,
        })
        self.ccm_state.configure(text="Previewed")
        self.app.schedule_process(immediate=True)

    def _apply_ccm(self):
        if self.session.ccm_result is None:
            return
        self._preview_ccm()
        self.previous_ccm = None
        self.ccm_state.configure(text="Applied")

    def _revert_ccm(self):
        if self.previous_ccm is None:
            return
        self.app.pipeline.module_by_id("color_correction_matrix").parameters = self.previous_ccm
        self.previous_ccm = None
        self.ccm_state.configure(text="Calculated")
        self.app.schedule_process(immediate=True)

    def _export_report(self):
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("JSON", "*.json"), ("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            self.sync_session()
            export_calibration_report(path, self.session)
        except Exception as exc:
            messagebox.showerror("导出报告失败", str(exc), parent=self)
            return
        self.status_var.set(f"Report: {path}")

    @staticmethod
    def _set_text(widget, text):
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def sync_session(self):
        self.session.name = self.session_name_var.get().strip()
        self.session.sensor_name = self.sensor_name_var.get().strip()
        self.session.illuminant = self.illuminant_var.get().strip() or "D65"
        self.session.notes = self.notes_var.get().strip()
        self.session.raw_metadata = copy.deepcopy(self.app.loaded.metadata)

    def select_auto_module(self, name: str) -> None:
        self.auto_panel.select_module(name)
        self.lift()
        self.focus_set()

    def get_ui_state(self) -> dict:
        return self.auto_panel.get_ui_state()

    def load_ui_state(self, state: dict) -> None:
        if isinstance(state, dict):
            self.auto_panel.load_ui_state(state)

    def close(self):
        self.generation += 1
        if hasattr(self, "auto_panel"):
            self.app.loaded_ui_state["calibration"] = self.get_ui_state()
            self.auto_panel.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.app.calibration_workspace = None
        self.destroy()

    def _revert_lsc_preview_on_close(self):
        # Preview is transient: closing the workspace without Apply restores
        # every module that still has an outstanding preview snapshot.
        self._revert_mesh()
        self._revert_awb()
        self._revert_ae()
        self._revert_ccm()


class InlineCalibrationWorkspace(ttk.Frame):
    """Calibration services hosted directly inside the main inspector."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="isp-inline-calibration"
        )
        self.current_future: Optional[Future] = None
        self.generation = 0
        self.status_var = tk.StringVar(value="Ready")
        self._init_state()
        self.auto_panel = AutoCalibrationPanel(self, self, app)
        self.auto_panel.pack(fill="both", expand=True)
        self.load_ui_state(
            getattr(app, "loaded_ui_state", {}).get(
                "calibration", {}
            )
        )

    @property
    def session(self) -> CalibrationSession:
        return self.app.calibration_session

    def _init_state(self) -> None:
        session = self.app.calibration_session
        self.session_name_var = tk.StringVar(value=session.name)
        self.sensor_name_var = tk.StringVar(value=session.sensor_name)
        self.illuminant_var = tk.StringVar(value=session.illuminant)
        self.notes_var = tk.StringVar(value=session.notes)
        self.mesh_rows_var = tk.IntVar(value=13)
        self.mesh_cols_var = tk.IntVar(value=17)
        self.mesh_stat_var = tk.StringVar(value="Median")
        self.ccm_rotation_var = tk.IntVar(value=0)
        self.ccm_flip_var = tk.BooleanVar(value=False)
        self.ccm_offset_var = tk.BooleanVar(value=True)
        self.ccm_ridge_var = tk.DoubleVar(value=0.015)
        self.ccm_exclude_var = tk.StringVar(value="")
        self.corner_vars = [
            tk.StringVar(value=value)
            for value in (
                "20,20", "620,20", "620,420", "20,420"
            )
        ]

    def _run_async(
        self, label: str, task: Callable, callback: Callable
    ) -> None:
        self.generation += 1
        generation = self.generation
        self.status_var.set(f"{label}…")
        if self.current_future is not None:
            self.current_future.cancel()
        future = self.executor.submit(task)
        self.current_future = future

        def poll() -> None:
            if not future.done():
                if self.winfo_exists():
                    self.after(20, poll)
                return
            if generation != self.generation or not self.winfo_exists():
                return
            try:
                result = future.result()
            except Exception as exc:
                self.status_var.set("Failed")
                messagebox.showerror(
                    f"{label} 失败", str(exc), parent=self
                )
                return
            self.status_var.set("Ready")
            callback(result)

        self.after(20, poll)

    def _full_stage(self, index: int):
        if not self.app.results:
            raise ISPError("请等待 ISP 预览处理完成")
        if self.app.roi_process_var.get():
            raise ISPError(
                "自动矫正前请关闭“仅处理 ROI”，以保持完整坐标"
            )
        return self.app.results[index]

    def _corners_from_roi(self) -> None:
        roi = self.app.roi
        if roi is None:
            messagebox.showinfo(
                "ColorChecker",
                "请先在主预览框选色卡外框。",
                parent=self,
            )
            return
        points = (
            (roi.x, roi.y),
            (roi.x2, roi.y),
            (roi.x2, roi.y2),
            (roi.x, roi.y2),
        )
        self._set_colorchecker_corners(points)

    def _parse_corners(self):
        corners = []
        for variable in self.corner_vars:
            tokens = variable.get().replace("，", ",").split(",")
            if len(tokens) != 2:
                raise ISPError("角点格式应为 x,y")
            corners.append((float(tokens[0]), float(tokens[1])))
        return corners

    def _edit_colorchecker_corners(self) -> None:
        try:
            stage_index = next(
                index
                for index, module in enumerate(
                    self.app.pipeline.modules
                )
                if module.module_id == "color_correction_matrix"
            )
            stage = self._full_stage(stage_index)
            if stage.domain != "rgb":
                raise ISPError("色卡四角编辑需要线性 RGB 输入")
            corners = self._parse_corners()
        except Exception as exc:
            messagebox.showerror(
                "ColorChecker", str(exc), parent=self
            )
            return
        ColorCheckerCornerEditor(
            self,
            stage.image,
            corners,
            int(self.ccm_rotation_var.get()),
            self._set_colorchecker_corners,
        )

    def _set_colorchecker_corners(self, corners) -> None:
        for variable, point in zip(self.corner_vars, corners):
            variable.set(f"{point[0]:.3f},{point[1]:.3f}")

    def sync_session(self) -> None:
        self.session.name = self.session_name_var.get().strip()
        self.session.sensor_name = self.sensor_name_var.get().strip()
        self.session.illuminant = (
            self.illuminant_var.get().strip() or "D65"
        )
        self.session.notes = self.notes_var.get().strip()
        self.session.raw_metadata = copy.deepcopy(
            self.app.loaded.metadata
        )

    def select_auto_module(self, name: str) -> None:
        self.auto_panel.select_module(name)

    def refresh_session(self) -> None:
        session = self.app.calibration_session
        self.session_name_var.set(session.name)
        self.sensor_name_var.set(session.sensor_name)
        self.illuminant_var.set(session.illuminant)
        self.notes_var.set(session.notes)
        self.auto_panel.refresh_session()

    def refresh_language(self) -> None:
        self.auto_panel.refresh_language()

    def get_ui_state(self) -> dict:
        return self.auto_panel.get_ui_state()

    def load_ui_state(self, state: dict) -> None:
        if isinstance(state, dict):
            self.auto_panel.load_ui_state(state)

    def close(self) -> None:
        self.generation += 1
        if self.current_future is not None:
            self.current_future.cancel()
        if hasattr(self, "auto_panel"):
            self.app.loaded_ui_state["calibration"] = (
                self.get_ui_state()
            )
            self.auto_panel.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()
