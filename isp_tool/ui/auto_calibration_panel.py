from __future__ import annotations

import copy
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Sequence

import numpy as np
import cv2
from PIL import Image, ImageTk

from ..auto_calibration import (
    AEAnalyzerAdapter,
    AWBAnalyzerAdapter,
    AutoCalibrationController,
    BLCAnalyzer,
    CCMAnalyzerAdapter,
    LSCAnalyzerAdapter,
    load_defect_map,
    save_defect_map,
)
from ..auto_calibration.dpc_calibrator import DefectMap, DefectPixel
from ..auto_calibration.persistence import save_recommendation
from ..bayer import channel_positions, resize_bayer_preview
from ..calibration.colorchecker import (
    colorchecker_reference,
    generate_colorchecker_grid,
    reorder_reference_indices,
    sample_colorchecker,
)
from ..calibration.ccm_solver import apply_ccm
from ..models import (
    AWBResult,
    CCMCalibrationResult,
    ISPError,
    ImageROI,
    ParameterRecommendation,
)
from ..preview import encode_display_uint8
from ..raw_io import PLAIN_EXTENSIONS, load_image
from .calibration_state import CalibrationStateMachine, CalibrationUIState
from .theme import COLORS, STATUS_COLORS
from .widgets import (
    ActionMenu,
    BusyOverlay,
    CalibrationFileItem,
    CollapsibleSection,
    FileList,
    InlineMessage,
    ROIItem,
    ROIList,
    ToastManager,
    validate_file_metadata,
)


class AutoCalibrationPanel(ttk.Frame):
    """Focused one-click calibration surface for the active ISP modules."""

    MODULES = (
        "BLC",
        "LSC",
        "AWB",
        "AE",
        "CCM",
    )
    RECOMMENDATION_IDS = {
        "BLC": ("auto_blc",),
        "LSC": ("flat_field_lsc",),
        "AWB": ("auto_white_balance",),
        "AE": ("auto_exposure",),
        "CCM": ("colorchecker_ccm",),
    }

    def __init__(self, parent, workspace, app):
        super().__init__(parent, padding=8)
        self.workspace = workspace
        self.app = app
        self.controller = AutoCalibrationController(
            app.pipeline,
            lambda: app.schedule_process(immediate=True),
            app.calibration_session,
        )
        self.result: Optional[ParameterRecommendation] = None
        self.dark_frames: List[np.ndarray] = []
        self.flat_frames: List[np.ndarray] = []
        self.dark_frame_paths: List[str] = []
        self.flat_frame_paths: List[str] = []
        self.dark_file_items: List[CalibrationFileItem] = []
        self.flat_file_items: List[CalibrationFileItem] = []
        self.noise_rois: List[ImageROI] = []
        self.noise_scope = "all"
        self.option_vars: Dict[str, tk.Variable] = {}
        self.states = {
            name: CalibrationStateMachine() for name in self.MODULES
        }
        self.analysis_base_image = None
        self.section_state = {
            "basic": True, "data": True
        }
        self.method_preferences: Dict[str, str] = {}
        self.direct_apply_after_analysis = ""
        self.toast = ToastManager(self)
        self._build()

    def _build(self) -> None:
        actions = ttk.Frame(self)
        self.action_bar = actions
        actions.pack(side="bottom", fill="x", pady=(7, 0))
        self.state_var = tk.StringVar(value="Not analyzed")
        ttk.Label(
            actions, textvariable=self.state_var, style="Muted.TLabel"
        ).pack(side="right")

        self.preview_banner = InlineMessage(self)
        self.preview_banner.pack(side="bottom", fill="x", pady=(6, 0))
        self.preview_banner.hide()

        self.module_var = tk.StringVar(value="BLC")

        workspace = ttk.Panedwindow(self, orient="horizontal")
        self.workspace_paned = workspace
        workspace.pack(fill="both", expand=True)
        middle = ttk.Frame(workspace, padding=(8, 6))
        workspace.add(middle, weight=1)

        navigation_model = ttk.Frame(self)
        self.module_list = tk.Listbox(
            navigation_model,
            bg=COLORS["panel_alt"], fg=COLORS["foreground"],
            selectbackground=COLORS["selection"],
            selectforeground="white", relief="flat", highlightthickness=1,
            highlightbackground=COLORS["border"], activestyle="none", width=23,
        )
        self.module_list.bind("<<ListboxSelect>>", self._navigation_changed)
        self.module_list.selection_set(0)
        ttk.Label(
            middle, text="矫正设置", style="Title.TLabel"
        ).pack(anchor="w", pady=(0, 4))
        self.source_var = tk.StringVar(value="Stage: — · Domain: — · ROI: Full")
        ttk.Label(
            middle, textvariable=self.source_var, style="Muted.TLabel",
            wraplength=370,
        ).pack(fill="x", pady=(0, 6))
        self.message = InlineMessage(middle)
        self.message.pack(fill="x")
        self.message.hide()
        self.busy = BusyOverlay(middle, self.cancel_analysis)
        self.busy.pack(fill="x")
        self.busy.hide()

        self.analyze_button = ttk.Button(
            middle, text="2  Analyze", style="Primary.TButton",
            command=self.analyze,
        )
        self.analyze_button.pack(side="bottom", fill="x", pady=(8, 0))
        options_shell = ttk.Frame(middle)
        options_shell.pack(fill="both", expand=True)
        self.options_canvas = tk.Canvas(
            options_shell, bg=COLORS["panel"], highlightthickness=0
        )
        options_scrollbar = ttk.Scrollbar(
            options_shell, orient="vertical",
            command=self.options_canvas.yview,
        )
        self.options_canvas.configure(
            yscrollcommand=options_scrollbar.set
        )
        options_scrollbar.pack(side="right", fill="y")
        self.options_canvas.pack(side="left", fill="both", expand=True)
        options_host = ttk.Frame(self.options_canvas)
        options_window = self.options_canvas.create_window(
            (0, 0), window=options_host, anchor="nw"
        )
        options_host.bind(
            "<Configure>",
            lambda _event: self.options_canvas.configure(
                scrollregion=self.options_canvas.bbox("all")
            ),
        )
        self.options_canvas.bind(
            "<Configure>",
            lambda event: self.options_canvas.itemconfigure(
                options_window, width=event.width
            ),
        )

        self.basic_section = CollapsibleSection(
            options_host, "方法与区域", expanded=True,
            on_toggle=lambda value: self._section_changed("basic", value),
        )
        self.basic_section.pack(fill="x")
        basic = self.basic_section.body
        self.method_label = ttk.Label(basic, text="Method / Mode")
        self.method_label.pack(anchor="w")
        self.method_var = tk.StringVar()
        self.method_combo = ttk.Combobox(
            basic, textvariable=self.method_var,
            state="readonly", width=23,
        )
        self.method_combo.pack(fill="x", pady=(2, 5))
        self.method_combo.bind(
            "<<ComboboxSelected>>", self._method_changed
        )
        self.method_help_var = tk.StringVar()
        self.method_help_label = ttk.Label(
            basic,
            textvariable=self.method_help_var,
            style="Muted.TLabel",
            wraplength=360,
        )
        self.use_roi_var = tk.BooleanVar(value=True)
        self.use_roi_check = ttk.Checkbutton(
            basic, text="Use current ROI", variable=self.use_roi_var,
            command=self._options_changed,
        )
        self.use_roi_check.pack(anchor="w")
        self.awb_region_var = tk.StringVar(value="Full Image")
        self.awb_region_frame = ttk.LabelFrame(
            basic, text="AWB 分析区域", padding=(8, 5)
        )
        for text, value in (
            ("全图：自动寻找中性区域", "Full Image"),
            ("当前 ROI：使用框选的中性灰/白区域", "Current ROI"),
        ):
            ttk.Radiobutton(
                self.awb_region_frame,
                text=text,
                variable=self.awb_region_var,
                value=value,
                command=self._awb_region_changed,
            ).pack(anchor="w", pady=1)
        self.awb_roi_status_var = tk.StringVar()
        ttk.Label(
            self.awb_region_frame,
            textvariable=self.awb_roi_status_var,
            style="Muted.TLabel",
            wraplength=340,
        ).pack(fill="x", pady=(4, 0))
        self.awb_region_frame.pack(fill="x", pady=(2, 0))

        self.data_section = CollapsibleSection(
            options_host, "校准图像（可选）", expanded=True,
            on_toggle=lambda value: self._section_changed("data", value),
        )
        self.data_section.pack(fill="both", expand=True, pady=(6, 0))
        data = self.data_section.body
        files = ttk.Frame(data)
        files.pack(fill="x")
        load_menu = ActionMenu(files, "Add")
        load_menu.add_command("Dark frames…", self._load_dark_frames)
        load_menu.add_command("Flat frames…", self._load_flat_frames)
        load_menu.pack(side="left")
        manage_menu = ActionMenu(files, "Manage")
        manage_menu.add_command("Validate all", self._validate_frame_lists)
        manage_menu.add_command(
            "Remove selected dark frame", self._remove_dark_frame,
            enabled=lambda: bool(self.dark_file_list.tree.selection())
            if hasattr(self, "dark_file_list") else False,
        )
        manage_menu.add_command(
            "Remove selected flat frame", self._remove_flat_frame,
            enabled=lambda: bool(self.flat_file_list.tree.selection())
            if hasattr(self, "flat_file_list") else False,
        )
        manage_menu.add_separator()
        manage_menu.add_command(
            "Clear dark frames", self._clear_dark_frames,
            enabled=lambda: bool(self.dark_frames),
        )
        manage_menu.add_command(
            "Clear flat frames", self._clear_flat_frames,
            enabled=lambda: bool(self.flat_frames),
        )
        manage_menu.pack(side="left")
        self.frame_status_var = tk.StringVar(
            value="Dark 0 · Flat 0"
        )
        ttk.Label(
            data, textvariable=self.frame_status_var, style="Muted.TLabel"
        ).pack(anchor="w", pady=(4, 3))
        self.dark_file_list = FileList(data, "Dark Frames")
        self.dark_file_list.pack(fill="x", pady=(3, 4))
        self.dark_file_list.configure_actions(
            self._remove_dark_frame,
            self._clear_dark_frames,
            self._validate_frame_lists,
        )
        self.flat_file_list = FileList(data, "Flat Frames")
        self.flat_file_list.pack(fill="x", pady=(3, 4))
        self.flat_file_list.configure_actions(
            self._remove_flat_frame,
            self._clear_flat_frames,
            self._validate_frame_lists,
        )

        # Analyzer tuning keeps safe defaults internally. The old Advanced
        # Options editor and Review/Measurements/Warnings/Artifacts pane were
        # intentionally removed from this quick-correction workspace.
        self.advanced = ttk.Frame(options_host)
        self._build_ccm_result_panel(options_host)
        router = getattr(self.app, "wheel_router", None)
        if router is not None:
            for widget in (
                self.module_list,
                self.options_canvas,
                self.dark_file_list.tree,
                self.flat_file_list.tree,
            ):
                router.register(widget, widget)
        self._module_changed()
        self._refresh_navigation()
        self._update_action_states()

    def _build_ccm_result_panel(self, parent) -> None:
        self.ccm_result_frame = ttk.LabelFrame(
            parent, text="CCM 结果验证", padding=8
        )
        self.ccm_verdict_var = tk.StringVar(value="")
        ttk.Label(
            self.ccm_result_frame,
            textvariable=self.ccm_verdict_var,
            wraplength=350,
        ).pack(fill="x")
        self.ccm_summary_var = tk.StringVar(value="")
        ttk.Label(
            self.ccm_result_frame,
            textvariable=self.ccm_summary_var,
            style="Muted.TLabel",
            wraplength=350,
        ).pack(fill="x", pady=(3, 6))
        matrices = ttk.Frame(self.ccm_result_frame)
        matrices.pack(fill="x")
        self.ccm_initial_matrix_var = tk.StringVar(value="")
        self.ccm_final_matrix_var = tk.StringVar(value="")
        for column, title, variable in (
            (0, "优化前 CCM", self.ccm_initial_matrix_var),
            (1, "优化后 CCM", self.ccm_final_matrix_var),
        ):
            box = ttk.Frame(matrices)
            box.grid(row=0, column=column, sticky="nsew", padx=(0, 6))
            ttk.Label(box, text=title).pack(anchor="w")
            ttk.Label(
                box,
                textvariable=variable,
                style="Mono.TLabel",
                justify="left",
            ).pack(anchor="w")
            matrices.columnconfigure(column, weight=1)

        previews = ttk.Frame(self.ccm_result_frame)
        previews.pack(fill="x", pady=(7, 5))
        self.ccm_before_preview = ttk.Label(
            previews, text="原图（显示映射）", anchor="center"
        )
        self.ccm_after_preview = ttk.Label(
            previews, text="校正图（显示映射）", anchor="center"
        )
        self.ccm_before_preview.grid(row=0, column=0, sticky="nsew")
        self.ccm_after_preview.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        previews.columnconfigure(0, weight=1)
        previews.columnconfigure(1, weight=1)
        self._ccm_preview_photos = []

        columns = (
            "id", "status", "input", "target", "corrected",
            "before", "after",
        )
        self.ccm_patch_tree = ttk.Treeview(
            self.ccm_result_frame,
            columns=columns,
            show="headings",
            height=8,
        )
        headings = {
            "id": "#",
            "status": "状态",
            "input": "输入 RGB",
            "target": "目标 RGB",
            "corrected": "校正 RGB",
            "before": "ΔE 前",
            "after": "ΔE 后",
        }
        for column in columns:
            self.ccm_patch_tree.heading(
                column, text=headings[column]
            )
            self.ccm_patch_tree.column(
                column,
                width=46 if column in {"id", "before", "after"} else 118,
                anchor="center",
                stretch=column not in {"id", "before", "after"},
            )
        patch_scroll = ttk.Scrollbar(
            self.ccm_result_frame,
            orient="horizontal",
            command=self.ccm_patch_tree.xview,
        )
        self.ccm_patch_tree.configure(
            xscrollcommand=patch_scroll.set
        )
        self.ccm_patch_tree.pack(fill="x")
        patch_scroll.pack(fill="x")
        router = getattr(self.app, "wheel_router", None)
        if router is not None:
            router.register(self.ccm_patch_tree, self.ccm_patch_tree)

    @staticmethod
    def _format_ccm_matrix(values) -> str:
        matrix = np.asarray(values, dtype=np.float64).reshape(3, 3)
        return "\n".join(
            " ".join(f"{value:+.4f}" for value in row)
            for row in matrix
        )

    @staticmethod
    def _format_rgb(values) -> str:
        if values is None:
            return "—"
        return "/".join(
            f"{float(value):.3f}" for value in values
        )

    @staticmethod
    def _format_metric(value) -> str:
        if value is None:
            return "—"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "—"
        return f"{numeric:.2f}" if np.isfinite(numeric) else "—"

    def _thumbnail_photo(self, rgb: np.ndarray) -> ImageTk.PhotoImage:
        values = np.asarray(rgb, dtype=np.float32)
        height, width = values.shape[:2]
        scale = min(170 / max(width, 1), 110 / max(height, 1), 1.0)
        if scale < 1.0:
            values = cv2.resize(
                values,
                (
                    max(1, round(width * scale)),
                    max(1, round(height * scale)),
                ),
                interpolation=cv2.INTER_AREA,
            )
        display = encode_display_uint8(
            values,
            getattr(self.app, "preview_exposure_ev", 0.0),
        )
        return ImageTk.PhotoImage(Image.fromarray(display))

    def _show_ccm_result(
        self,
        result: ParameterRecommendation,
        base_image: Optional[np.ndarray] = None,
    ) -> None:
        measurements = result.measurements
        safe = bool(measurements.get("safe_to_apply", False))
        reasons = list(measurements.get("rejection_reasons", []))
        self.ccm_verdict_var.set(
            "✓ 结果通过安全检查，可以应用"
            if safe
            else "⚠ 结果未通过安全检查，不会自动应用"
            + (f"：{'；'.join(reasons)}" if reasons else "")
        )
        before = measurements.get("delta_e_before", {})
        initial = measurements.get("delta_e_initial", {})
        after = measurements.get("delta_e_after", {})
        row_sums = measurements.get("row_sums") or []
        diagonal_values = measurements.get("diagonal_values") or []
        negative_off_diagonal_count = int(
            measurements.get("negative_off_diagonal_count", 0)
        )
        self.ccm_summary_var.set(
            "平均 ΔE "
            f"{before.get('mean', 0):.2f} → "
            f"{initial.get('mean', 0):.2f} → "
            f"{after.get('mean', 0):.2f}；最大 ΔE "
            f"{before.get('max', 0):.2f} → "
            f"{after.get('max', 0):.2f}\n"
            "行和 "
            + ", ".join(f"{float(value):.3f}" for value in row_sums)
            + "\n主对角 "
            + ", ".join(
                f"{float(value):.3f}" for value in diagonal_values
            )
            + f"；负非对角 {negative_off_diagonal_count}/6"
            + f"；矩阵条件数 {float(measurements.get('condition_number', 0)):.2f}；"
            f"整图负值 {float(measurements.get('frame_negative_ratio', measurements.get('negative_ratio', 0))) * 100:.1f}% / "
            f"溢出 {float(measurements.get('frame_overflow_ratio', measurements.get('overflow_ratio', 0))) * 100:.1f}%"
        )
        initial_matrix = measurements.get("initial_matrix")
        final_matrix = measurements.get("matrix")
        self.ccm_initial_matrix_var.set(
            self._format_ccm_matrix(initial_matrix)
            if initial_matrix is not None else "—"
        )
        self.ccm_final_matrix_var.set(
            self._format_ccm_matrix(final_matrix)
            if final_matrix is not None else "—"
        )
        self.ccm_patch_tree.delete(
            *self.ccm_patch_tree.get_children()
        )
        for patch in measurements.get("patches", []):
            diagnostics = patch.get("diagnostics", {})
            status = (
                "有效"
                if diagnostics.get("valid", True)
                else "异常："
                + "、".join(
                    map(str, diagnostics.get("reasons", []))
                )
            )
            self.ccm_patch_tree.insert(
                "",
                "end",
                values=(
                    patch.get("patch_id", ""),
                    status,
                    self._format_rgb(patch.get("measured_rgb", (0, 0, 0))),
                    self._format_rgb(patch.get("reference_rgb", (0, 0, 0))),
                    self._format_rgb(
                        diagnostics.get("corrected_rgb", (0, 0, 0))
                    ),
                    self._format_metric(
                        diagnostics.get("delta_e_before")
                    ),
                    self._format_metric(
                        diagnostics.get("delta_e_after")
                    ),
                ),
            )
        if base_image is None and self.app.results:
            try:
                base_image = self.app.results[
                    self._stage_before("color_correction_matrix")
                ].image
            except Exception:
                base_image = None
        self._ccm_preview_photos = []
        if (
            base_image is not None
            and final_matrix is not None
            and np.asarray(base_image).ndim == 3
        ):
            offset = np.asarray(
                measurements.get("offset", (0, 0, 0)),
                dtype=np.float64,
            )
            corrected = apply_ccm(
                base_image, np.asarray(final_matrix), offset
            )
            before_photo = self._thumbnail_photo(base_image)
            after_photo = self._thumbnail_photo(corrected)
            self._ccm_preview_photos = [before_photo, after_photo]
            self.ccm_before_preview.configure(
                image=before_photo, text="原图"
            )
            self.ccm_after_preview.configure(
                image=after_photo, text="校正图"
            )
        else:
            self.ccm_before_preview.configure(
                image="", text="原图预览不可用"
            )
            self.ccm_after_preview.configure(
                image="", text="校正预览不可用"
            )
        if not self.ccm_result_frame.winfo_manager():
            self.ccm_result_frame.pack(
                fill="x", pady=(7, 0)
            )

    def _module_changed(self, _event=None) -> None:
        if self.controller.has_preview:
            self.controller.revert()
            previous = next(
                (
                    state for state in self.states.values()
                    if state.state == CalibrationUIState.PREVIEWING
                ),
                None,
            )
            if previous is not None:
                previous.transition(CalibrationUIState.SUGGESTED)
            self.preview_banner.hide()
            self.toast.show("未应用的 Preview 已自动恢复", "info")
        values: Dict[str, Sequence[str]] = {
            "BLC": (
                "Current RAW",
                "Current Dark ROI",
                "Optical Black ROI",
                "External Dark Frame",
            ),
            "LSC": ("Median", "Trimmed Mean"),
            "AWB": (
                "Robust Neutral",
                "ROI Neutral",
                "Gray World",
                "Shades of Gray",
                "White Patch",
            ),
            "AE": ("Mean Luma", "Median Luma", "Percentile", "Highlight Protected"),
            "CCM": ("ColorChecker Patches",),
        }
        choices = tuple(values[self.module_var.get()])
        self.method_combo.configure(values=choices)
        preferred = self.method_preferences.get(self.module_var.get(), choices[0])
        self.method_var.set(preferred if preferred in choices else choices[0])
        self._update_module_specific_layout()
        self._build_advanced_options()
        result = self._saved_result(self.module_var.get())
        self.result = result
        if self.module_var.get() != "CCM":
            self.ccm_result_frame.pack_forget()
        if result is not None:
            machine = self.states[self.module_var.get()]
            if machine.state == CalibrationUIState.NOT_ANALYZED:
                machine.state = (
                    CalibrationUIState.APPLIED
                    if result.applied else CalibrationUIState.SUGGESTED
                )
                machine.parameter_snapshot = copy.deepcopy(
                    result.suggested_parameters
                    if result.applied else result.current_parameters
                )
            self.message.show(
                f"上次矫正：Confidence {result.confidence * 100:.1f}%"
                + (" · 已应用" if result.applied else ""),
                "success",
            )
            if self.module_var.get() == "CCM":
                self._show_ccm_result(result)
        else:
            self.message.hide()
            if self.module_var.get() == "CCM":
                self.ccm_result_frame.pack_forget()
        self._update_source_summary()
        self._update_action_states()
        self._refresh_navigation()

    def _navigation_changed(self, _event=None) -> None:
        selection = self.module_list.curselection()
        if not selection:
            return
        name = self.MODULES[int(selection[0])]
        if name == self.module_var.get():
            return
        if (
            self.states[self.module_var.get()].state
            == CalibrationUIState.RUNNING
        ):
            self.cancel_analysis()
        self.module_var.set(name)
        self._module_changed()

    def select_module(self, name: str) -> None:
        if name not in self.MODULES:
            return
        if name == self.module_var.get():
            index = self.MODULES.index(name)
            self.module_list.selection_clear(0, "end")
            self.module_list.selection_set(index)
            self.module_list.see(index)
            return
        if (
            name != self.module_var.get()
            and self.states[self.module_var.get()].state
            == CalibrationUIState.RUNNING
        ):
            self.cancel_analysis()
        index = self.MODULES.index(name)
        self.module_list.selection_clear(0, "end")
        self.module_list.selection_set(index)
        self.module_list.see(index)
        self.module_var.set(name)
        self._module_changed()
        target_id = {
            "BLC": "black_level_correction",
            "LSC": "lens_shading_correction",
            "AWB": "white_balance",
            "CCM": "color_correction_matrix",
        }.get(name)
        if target_id is not None:
            target_index = next(
                (
                    position
                    for position, module in enumerate(
                        self.app.pipeline.modules
                    )
                    if module.module_id == target_id
                ),
                None,
            )
            if (
                target_index is not None
                and target_index
                != self.app.selected_module_index
            ):
                self.app.pipeline_list.selection_clear(0, "end")
                self.app.pipeline_list.selection_set(target_index)
                self.app.pipeline_list.see(target_index)
                self.app._on_module_select()

    def _saved_result(self, module: str) -> Optional[ParameterRecommendation]:
        recommendations = self.app.calibration_session.auto_recommendations
        for identifier in self.RECOMMENDATION_IDS[module]:
            if identifier in recommendations:
                return recommendations[identifier]
        return None

    def _refresh_navigation(self) -> None:
        selected = self.MODULES.index(self.module_var.get())
        symbols = {
            CalibrationUIState.NOT_ANALYZED: "○",
            CalibrationUIState.RUNNING: "↻",
            CalibrationUIState.SUGGESTED: "●",
            CalibrationUIState.PREVIEWING: "◐",
            CalibrationUIState.APPLIED: "✓",
            CalibrationUIState.STALE: "!",
            CalibrationUIState.FAILED: "×",
            CalibrationUIState.CANCELLED: "–",
        }
        self.module_list.delete(0, "end")
        for name in self.MODULES:
            self.module_list.insert(
                "end", f" {symbols[self.states[name].state]}  {name}"
            )
            self.module_list.itemconfig(
                self.module_list.size() - 1,
                foreground=STATUS_COLORS[self.states[name].state.value],
            )
        self.module_list.selection_set(selected)

    def _section_changed(self, key: str, expanded: bool) -> None:
        self.section_state[key] = bool(expanded)

    def _update_module_specific_layout(self) -> None:
        is_awb = self.module_var.get() == "AWB"
        uses_calibration_files = self.module_var.get() in {
            "BLC", "LSC",
        }
        if is_awb:
            if self.method_var.get() == "ROI Neutral":
                self.awb_region_var.set("Current ROI")
            self.use_roi_var.set(
                self.awb_region_var.get() == "Current ROI"
            )
            self.method_label.configure(text="AWB 方法")
            self.use_roi_check.pack_forget()
            self.method_help_label.pack(
                fill="x", pady=(0, 5), after=self.method_combo
            )
            self.awb_region_frame.pack(
                fill="x", pady=(2, 0),
                after=self.method_help_label,
            )
            self.data_section.pack_forget()
            self._refresh_awb_quick_options()
        else:
            self.method_label.configure(text="Method / Mode")
            self.method_help_label.pack_forget()
            self.awb_region_frame.pack_forget()
            if not self.use_roi_check.winfo_manager():
                self.use_roi_check.pack(anchor="w")
            if (
                uses_calibration_files
                and not self.data_section.winfo_manager()
            ):
                self.data_section.pack(
                    fill="both",
                    expand=True,
                    pady=(6, 0),
                )
            elif (
                not uses_calibration_files
                and self.data_section.winfo_manager()
            ):
                self.data_section.pack_forget()
            if self.direct_apply_after_analysis == "AWB":
                self.direct_apply_after_analysis = ""

    def _method_changed(self, _event=None) -> None:
        if (
            self.module_var.get() == "AWB"
            and self.method_var.get() == "ROI Neutral"
        ):
            self.awb_region_var.set("Current ROI")
            self.use_roi_var.set(True)
        self._refresh_awb_quick_options()
        self._options_changed()

    def _awb_region_changed(self) -> None:
        use_roi = self.awb_region_var.get() == "Current ROI"
        self.use_roi_var.set(use_roi)
        self._refresh_awb_quick_options()
        self._options_changed()

    def _refresh_awb_quick_options(self) -> None:
        descriptions = {
            "Robust Neutral": "稳健中性区域（推荐）：自动排除彩色物体、纹理和过曝像素。",
            "ROI Neutral": "ROI 中性区域：假定框选内容本身应为中性灰或白，适合灰卡。",
            "Gray World": "灰度世界：假定整幅场景的平均颜色接近中性。",
            "Shades of Gray": "Shades of Gray：比灰度世界更强调较亮像素。",
            "White Patch": "白点法：根据未过曝的高亮像素估算照明颜色。",
        }
        self.method_help_var.set(
            descriptions.get(self.method_var.get(), "")
        )
        roi = getattr(self.app, "roi", None)
        if self.awb_region_var.get() == "Full Image":
            self.awb_roi_status_var.set(
                "当前使用完整 LSC 输出；算法会排除暗部、过曝和高纹理样本。"
                "去马赛克前的 RAW 马赛克整体偏绿属于正常 CFA 排列，"
                "请以 Demosaic 输出判断最终白平衡。"
            )
        elif roi is None:
            self.awb_roi_status_var.set(
                "尚未框选 ROI。请回到主预览框选中性灰/白区域。"
            )
        else:
            self.awb_roi_status_var.set(
                f"当前 ROI：x={roi.x}, y={roi.y}, "
                f"{roi.width}×{roi.height}。RAW 马赛克偏绿是正常的，"
                "请以 Demosaic 输出判断最终白平衡。"
            )

    def _options_changed(self) -> None:
        if self.method_var.get():
            self.method_preferences[self.module_var.get()] = self.method_var.get()
        self._update_source_summary()
        machine = self.states[self.module_var.get()]
        if machine.state == CalibrationUIState.PREVIEWING:
            self.controller.revert()
            machine.transition(CalibrationUIState.SUGGESTED)
            machine.transition(CalibrationUIState.STALE)
            self.preview_banner.hide()
            self.toast.show("Preview 已恢复，建议已过期", "warning")
        elif machine.state in {
            CalibrationUIState.SUGGESTED,
            CalibrationUIState.APPLIED,
        }:
            machine.transition(CalibrationUIState.STALE)
        else:
            return
        if machine.state == CalibrationUIState.STALE:
            self.message.show(
                "分析参数已变化，当前 Recommendation 已过期，请重新 Analyze。",
                "warning",
            )
            self._update_action_states()
            self._refresh_navigation()
            self._sync_main_status()

    def _update_source_summary(self) -> None:
        if self.module_var.get() == "AWB":
            self._refresh_awb_quick_options()
        if not self.app.results:
            self.source_var.set("Stage: waiting for preview")
            return
        try:
            index = {
                "BLC": 0,
                "LSC": self._stage_before("lens_shading_correction"),
                "AWB": self._stage_before("white_balance"),
                "AE": self._stage_before("white_balance"),
                "CCM": self._stage_before("color_correction_matrix"),
            }[self.module_var.get()]
            stage = self.app.results[index]
            roi = self.app.roi
            roi_text = (
                f"{roi.x},{roi.y} {roi.width}×{roi.height}"
                if roi and self.use_roi_var.get() else "Full"
            )
            self.source_var.set(
                f"Stage {index}: {stage.name} · {stage.domain.upper()} · "
                f"{stage.image.shape[1]}×{stage.image.shape[0]} · ROI {roi_text}"
            )
            if self.module_var.get() == "BLC":
                if (
                    self.method_var.get() == "External Dark Frame"
                    and self.dark_frames
                ):
                    sample = self.dark_frames[0]
                elif roi and (
                    self.use_roi_var.get()
                    or "ROI" in self.method_var.get()
                ):
                    ys, xs = roi.slices()
                    sample = stage.image[ys, xs]
                else:
                    sample = stage.image
                p99 = float(np.percentile(sample, 99)) if sample.size else 0.0
                metadata = self.app.loaded.metadata
                dark_limit = max(metadata.black_level) + 0.1 * (
                    metadata.white_level - max(metadata.black_level)
                )
                sample_count = (
                    len(self.dark_frames)
                    if self.method_var.get() == "External Dark Frame"
                    else int(sample.size)
                )
                self.source_var.set(
                    self.source_var.get()
                    + f"\nSource {self.method_var.get()} · Samples "
                    f"{sample_count} · Dark-field hint "
                    f"{'Yes' if p99 <= dark_limit else 'No'}"
                )
            if self.module_var.get() == "CCM":
                rotation_value = self.option_vars.get(
                    "rotation", self.workspace.ccm_rotation_var
                ).get()
                flip_value = self.option_vars.get(
                    "flip", self.workspace.ccm_flip_var
                ).get()
                excluded_value = str(self.option_vars.get(
                    "excluded_patches", self.workspace.ccm_exclude_var
                ).get())
                excluded = {
                    token.strip()
                    for token in excluded_value.replace("，", ",").split(",")
                    if token.strip()
                }
                self.source_var.set(
                    self.source_var.get()
                    + f"\nLinear RGB only · Illuminant "
                    f"{self.workspace.illuminant_var.get()} · Rotation "
                    f"{rotation_value}° · Flip "
                    f"{'Yes' if flip_value else 'No'} · "
                    f"Valid patches {max(0, 24 - len(excluded))}/24 · "
                    "Gamma/tone-mapped input is prohibited"
                )
        except Exception:
            self.source_var.set("Stage/input validation pending")

    def _stage_before(self, module_id: str) -> int:
        """Return the result index feeding a pipeline module."""
        return next(
            index
            for index, module in enumerate(self.app.pipeline.modules)
            if module.module_id == module_id
        )

    def _update_action_states(self) -> None:
        machine = self.states[self.module_var.get()]
        state = machine.state
        self.analyze_button.configure(
            text=(
                "正在矫正…"
                if state == CalibrationUIState.RUNNING
                else "重新矫正并应用"
                if state == CalibrationUIState.APPLIED
                else "矫正并应用"
            ),
            command=self.correct_and_apply_current,
            style="Primary.TButton",
            state=(
                "disabled"
                if state == CalibrationUIState.RUNNING
                else "normal"
            ),
        )
        self.state_var.set(
            {
                CalibrationUIState.NOT_ANALYZED: "待矫正",
                CalibrationUIState.RUNNING: "处理中",
                CalibrationUIState.SUGGESTED: "已计算",
                CalibrationUIState.PREVIEWING: "应用中",
                CalibrationUIState.APPLIED: "已应用",
                CalibrationUIState.STALE: "需重新矫正",
                CalibrationUIState.FAILED: "失败",
                CalibrationUIState.CANCELLED: "已取消",
            }[state]
        )

    def _sync_main_status(self) -> None:
        self.app._refresh_pipeline_list()
        self.app._refresh_auto_summary()
        module = self.app.pipeline.modules[
            self.app.selected_module_index
        ]
        self.app._build_parameter_editor(module)
        self.app._refresh_module_state()

    def _build_advanced_options(self) -> None:
        self.option_vars = {}
        module = self.module_var.get()
        specifications = {
            "BLC": (
                ("Statistic", "statistic", "choice", "Median", ("Median", "Trimmed Mean", "Mean")),
                ("Trim fraction", "trim_fraction", "float", 0.05, ()),
            ),
            "LSC": (
                ("Mesh rows", "rows", "int", int(self.workspace.mesh_rows_var.get()), ()),
                ("Mesh cols", "cols", "int", int(self.workspace.mesh_cols_var.get()), ()),
                ("Smoothing", "smoothing", "float", 0.7, ()),
                ("Trim fraction", "trim_fraction", "float", 0.05, ()),
            ),
            "AWB": (
                ("Low percentile", "low_percentile", "float", 2.0, ()),
                ("High percentile", "high_percentile", "float", 98.0, ()),
                ("Neutral tolerance", "neutral_tolerance", "float", 0.18, ()),
                ("Gain limit", "gain_limit", "float", 8.0, ()),
            ),
            "AE": (
                ("Target", "target_level", "float", 0.45, ()),
                ("Measure percentile", "measurement_percentile", "float", 50.0, ()),
                ("Highlight percentile", "highlight_percentile", "float", 99.5, ()),
                ("Maximum gain", "maximum_gain", "float", 8.0, ()),
                ("Max clipping", "maximum_allowed_clipping", "float", 0.01, ()),
            ),
            "CCM": (
                ("Rotation", "rotation", "choice", str(self.workspace.ccm_rotation_var.get()), ("0", "90", "180", "270")),
                ("Flip", "flip", "bool", bool(self.workspace.ccm_flip_var.get()), ()),
                ("Include offset", "include_offset", "bool", bool(self.workspace.ccm_offset_var.get()), ()),
                ("Ridge", "ridge", "float", float(self.workspace.ccm_ridge_var.get()), ()),
                ("Excluded patches", "excluded_patches", "text", self.workspace.ccm_exclude_var.get(), ()),
            ),
        }[module]
        for _label, key, kind, default, _choices in specifications:
            if kind == "int":
                variable: tk.Variable = tk.IntVar(value=default)
            elif kind == "float":
                variable = tk.DoubleVar(value=default)
            elif kind == "bool":
                variable = tk.BooleanVar(value=default)
            else:
                variable = tk.StringVar(value=default)
            self.option_vars[key] = variable
            variable.trace_add(
                "write", lambda *_args: self._options_changed()
            )

    def _option_values(self) -> Dict[str, object]:
        return {
            key: variable.get()
            for key, variable in self.option_vars.items()
        }

    def _ccm_corners_from_roi(self) -> None:
        if self.app.roi is None:
            self.message.show(
                "请先在主预览中框选 ColorChecker 外框。",
                "warning",
            )
            return
        self.workspace._corners_from_roi()
        self.message.show("ColorChecker 角点已从当前 ROI 更新。", "success")
        self._options_changed()

    def _load_dark_frames(self) -> None:
        (
            self.dark_frames,
            self.dark_frame_paths,
            self.dark_file_items,
        ) = self._load_frames("Load dark RAW frames")
        self._sync_file_lists()
        self._update_frame_status()
        self._show_frame_load_result("暗场", self.dark_frames, self.dark_file_items)

    def _load_flat_frames(self) -> None:
        (
            self.flat_frames,
            self.flat_frame_paths,
            self.flat_file_items,
        ) = self._load_frames("Load flat-field RAW frames")
        self._sync_file_lists()
        self._update_frame_status()
        self._show_frame_load_result("平场", self.flat_frames, self.flat_file_items)

    def _show_frame_load_result(
        self,
        label: str,
        frames: List[np.ndarray],
        items: List[CalibrationFileItem],
    ) -> None:
        invalid = len(items) - len(frames)
        self.toast.show(
            f"已加载 {len(frames)} 张{label}"
            + (f"，{invalid} 张未通过验证" if invalid else ""),
            "warning" if invalid else "success",
        )
        if invalid:
            self.message.show(
                "元数据不一致或读取失败的文件已在列表中标红，"
                "不会参与分析。",
                "warning",
            )

    def _load_frames(
        self, title: str
    ) -> tuple[
        List[np.ndarray], List[str], List[CalibrationFileItem]
    ]:
        paths = filedialog.askopenfilenames(
            parent=self,
            title=title,
            filetypes=[
                ("RAW / image", "*.raw *.bin *.dat *.dng *.nef *.cr2 *.arw *.tif *.tiff *.png"),
                ("All", "*.*"),
            ],
        )
        if not paths:
            return [], [], []
        frames: List[np.ndarray] = []
        valid_paths: List[str] = []
        items: List[CalibrationFileItem] = []
        reference = self.app.loaded
        for path in paths:
            try:
                metadata = (
                    copy.deepcopy(reference.metadata)
                    if Path(path).suffix.lower() in PLAIN_EXTENSIONS else None
                )
                loaded = load_image(path, metadata)
                item = CalibrationFileItem(
                    str(path),
                    loaded.metadata.width,
                    loaded.metadata.height,
                    loaded.metadata.bit_depth,
                    loaded.metadata.bayer_pattern,
                )
                item.validation = validate_file_metadata(
                    item, reference.metadata
                )
                if loaded.domain != "bayer":
                    item.validation = "Invalid: not Bayer"
                if item.validation != "Valid":
                    items.append(item)
                    continue
                frame = loaded.image
                if frame.shape != self.app.preview_image.shape:
                    frame = resize_bayer_preview(
                        frame,
                        loaded.metadata.bayer_pattern,
                        max_side=self.app.preview_max_side,
                    )
                if frame.shape != self.app.preview_image.shape:
                    item.validation = "Mismatch: preview size"
                    items.append(item)
                    continue
                frames.append(np.asarray(frame, np.float32))
                valid_paths.append(str(path))
                items.append(item)
            except Exception as exc:
                items.append(CalibrationFileItem(
                    str(path), 0, 0, 0, "—", loaded=False,
                    validation="Read failed", message=str(exc),
                ))
        if "dark" in title.lower():
            prefix = "dark_frame_"
        else:
            prefix = "flat_frame_"
        session_assets = self.app.calibration_session.external_assets
        for key in list(session_assets):
            if key.startswith(prefix):
                session_assets.pop(key)
        for index, path in enumerate(valid_paths):
            session_assets[f"{prefix}{index}"] = str(path)
        return frames, valid_paths, items

    def _update_frame_status(self) -> None:
        self.frame_status_var.set(
            f"Dark {len(self.dark_frames)} · "
            f"Flat {len(self.flat_frames)}"
        )
        self._update_source_summary()

    def _sync_file_lists(self) -> None:
        self.dark_file_list.set_items(self.dark_file_items)
        self.flat_file_list.set_items(self.flat_file_items)

    def _validate_frame_lists(self) -> None:
        reference = self.app.loaded.metadata
        invalid = 0
        for file_list in (self.dark_file_list, self.flat_file_list):
            items = file_list.items()
            for item in items:
                if item.loaded:
                    item.validation = validate_file_metadata(item, reference)
                invalid += item.validation != "Valid"
            file_list.set_items(items)
        if invalid:
            self.message.show(
                f"{invalid} 个标定文件的元数据与当前 RAW 不一致。",
                "warning",
            )
        else:
            self.message.show("所有标定文件验证通过。", "success")

    def _remove_dark_frame(self) -> None:
        selected = self.dark_file_list.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        item = self.dark_file_items.pop(index)
        if item.path in self.dark_frame_paths:
            frame_index = self.dark_frame_paths.index(item.path)
            self.dark_frame_paths.pop(frame_index)
            self.dark_frames.pop(frame_index)
        self._sync_file_lists()
        self._sync_session_frame_assets("dark_frame_", self.dark_frame_paths)
        self._update_frame_status()
        self._options_changed()

    def _clear_dark_frames(self) -> None:
        self.dark_frames = []
        self.dark_frame_paths = []
        self.dark_file_items = []
        self._sync_file_lists()
        self._sync_session_frame_assets("dark_frame_", [])
        self._update_frame_status()
        self._options_changed()

    def _remove_flat_frame(self) -> None:
        selected = self.flat_file_list.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        item = self.flat_file_items.pop(index)
        if item.path in self.flat_frame_paths:
            frame_index = self.flat_frame_paths.index(item.path)
            self.flat_frame_paths.pop(frame_index)
            self.flat_frames.pop(frame_index)
        self._sync_file_lists()
        self._sync_session_frame_assets("flat_frame_", self.flat_frame_paths)
        self._update_frame_status()
        self._options_changed()

    def _clear_flat_frames(self) -> None:
        self.flat_frames = []
        self.flat_frame_paths = []
        self.flat_file_items = []
        self._sync_file_lists()
        self._sync_session_frame_assets("flat_frame_", [])
        self._update_frame_status()
        self._options_changed()

    def _sync_session_frame_assets(
        self, prefix: str, paths: List[str]
    ) -> None:
        assets = self.app.calibration_session.external_assets
        for key in list(assets):
            if key.startswith(prefix):
                assets.pop(key)
        for index, path in enumerate(paths):
            assets[f"{prefix}{index}"] = str(path)

    def _add_noise_roi(self) -> None:
        if self.app.roi is None:
            self.message.show(
                "请先在主界面选择一个平坦 Noise ROI。",
                "warning",
            )
            return
        roi = copy.deepcopy(self.app.roi)
        if roi not in self.noise_rois:
            self.noise_rois.append(roi)
            self.roi_list.add(ROIItem(roi))
        self._update_frame_status()
        self.toast.show("Noise ROI 已添加", "success")
        self._options_changed()

    def _clear_noise_rois(self) -> None:
        self.noise_rois = []
        self.roi_list.clear()
        self._update_frame_status()
        self._options_changed()

    def _remove_noise_roi(self) -> None:
        removed = self.roi_list.remove_selected()
        if removed is None:
            return
        self.noise_rois = [item.roi for item in self.roi_list.items()]
        self._update_frame_status()
        self._options_changed()

    def _select_noise_roi(self, item: ROIItem) -> None:
        self.app.roi = copy.deepcopy(item.roi)
        self.app._update_roi_label()
        self.app.render_current()

    def _analyze_selected_noise_roi(self) -> None:
        selection = self.roi_list.tree.selection()
        if not selection:
            self.message.show("请先选择一个 Noise ROI。", "warning")
            return
        self.noise_scope = "selected"
        self.select_module("Noise Profile")
        self.analyze()

    def _analyze_all_noise_rois(self) -> None:
        self.noise_scope = "all"
        self.select_module("Noise Profile")
        self.analyze()

    def _import_dpc_map(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[
                ("DPC Map", "*.json *.csv *.npz"),
                ("All", "*.*"),
            ],
        )
        if not path:
            return
        try:
            defect_map = load_defect_map(path, self.app.loaded.metadata)
            array = defect_map.to_array()
            if array.shape != self.app.preview_image.shape[:2]:
                raise ISPError(
                    f"坏点表尺寸 {array.shape[1]}×{array.shape[0]} 与当前预览 "
                    f"{self.app.preview_image.shape[1]}×{self.app.preview_image.shape[0]} 不一致"
                )
            module = self.app.pipeline.module_by_id(
                "defective_pixel_correction"
            )
            module.set_defect_map(array)
            module.parameters["mode"] = "Static Map"
            self.app.schedule_process(immediate=True)
        except Exception as exc:
            messagebox.showerror("Import DPC Map", str(exc), parent=self)
            return
        self.toast.show("DPC Map 已导入", "success")
        self.state_var.set(
            f"Imported DPC Map · {len(defect_map.pixels)} defects"
        )

    def _export_dpc_map(self) -> None:
        defect_map = None
        if (
            self.result is not None
            and isinstance(self.result.measurements.get("defect_map"), dict)
        ):
            defect_map = DefectMap.from_dict(
                self.result.measurements["defect_map"]
            )
        if defect_map is None:
            module = self.app.pipeline.module_by_id(
                "defective_pixel_correction"
            )
            if module.defect_map is not None:
                lookup = {
                    tuple(position): name
                    for name, position in channel_positions(
                        self.app.loaded.metadata.bayer_pattern
                    ).items()
                }
                pixels = []
                ys, xs = np.nonzero(module.defect_map)
                for y, x in zip(ys, xs):
                    pixels.append(DefectPixel(
                        int(x),
                        int(y),
                        lookup[(int(y) % 2, int(x) % 2)],
                        "hot" if module.defect_map[y, x] == 1 else "dead",
                        1.0,
                        1.0,
                    ))
                defect_map = DefectMap(
                    module.defect_map.shape[1],
                    module.defect_map.shape[0],
                    self.app.loaded.metadata.bayer_pattern,
                    pixels,
                    "Current DPC module",
                )
        if defect_map is None:
            self.message.show(
                "尚无可导出的静态坏点表。",
                "warning",
            )
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".json",
            filetypes=[
                ("JSON", "*.json"),
                ("CSV", "*.csv"),
                ("NPZ", "*.npz"),
            ],
        )
        if not path:
            return
        try:
            save_defect_map(path, defect_map)
        except Exception as exc:
            messagebox.showerror("Export DPC Map", str(exc), parent=self)
            return
        self.toast.show("DPC Map 已导出", "success")
        self.state_var.set(f"Exported DPC Map: {path}")

    def correct_and_apply_current(self) -> None:
        module_name = self.module_var.get()
        if module_name == "AWB":
            self._refresh_awb_quick_options()
            use_roi = self.awb_region_var.get() == "Current ROI"
            if self.method_var.get() == "ROI Neutral":
                use_roi = True
                self.awb_region_var.set("Current ROI")
            self.use_roi_var.set(use_roi)
            if use_roi and self.app.roi is None:
                self.message.show(
                    "请先在主预览框选中性灰或白色 ROI，再点击“矫正并应用”。",
                    "warning",
                )
                self.toast.show("AWB ROI 尚未框选", "warning")
                return
        machine = self.states[module_name]
        if machine.state == CalibrationUIState.RUNNING:
            return
        if machine.state == CalibrationUIState.PREVIEWING:
            self.revert()
        if machine.state in {
            CalibrationUIState.SUGGESTED,
            CalibrationUIState.APPLIED,
        }:
            machine.transition(CalibrationUIState.STALE)
        self.direct_apply_after_analysis = module_name
        if not self.analyze():
            self.direct_apply_after_analysis = ""

    def correct_and_apply_awb(self) -> None:
        """Compatibility alias for the focused AWB action."""
        if self.module_var.get() == "AWB":
            self.correct_and_apply_current()

    def analyze(self) -> bool:
        if self.controller.has_preview:
            self.controller.revert()
            machine = self.states[self.module_var.get()]
            if machine.state == CalibrationUIState.PREVIEWING:
                machine.transition(CalibrationUIState.SUGGESTED)
            self.preview_banner.hide()
            self.toast.show("Preview 已恢复，请在主预览刷新后重新 Analyze", "info")
            self._update_action_states()
            return False
        machine = self.states[self.module_var.get()]
        if not machine.can_analyze:
            return False
        try:
            self.controller.session = self.app.calibration_session
            analyzer, stage_index, options = self._analysis_request()
            stage = self.workspace._full_stage(stage_index)
            override_image = options.pop("override_image", None)
            force_roi = bool(options.pop("_force_roi", False))
            force_full = bool(options.pop("_force_full", False))
            image = (
                np.asarray(override_image, np.float32).copy()
                if override_image is not None else stage.image.copy()
            )
            metadata = copy.deepcopy(self.app.loaded.metadata)
            roi = (
                None if force_full
                else self.app.roi
                if (self.use_roi_var.get() or force_roi)
                else None
            )
            generation, token = self.controller.begin_analysis()
            target_module = self.app.pipeline.module_by_id(
                analyzer.target_module_id or analyzer.module_id
            )
            machine.start(target_module.parameters)
        except Exception as exc:
            self.message.show(str(exc), "error")
            return False
        self.analysis_base_image = image if image.ndim == 3 else None
        self.message.hide()
        self.busy.show(
            f"Analyze {self.module_var.get()}",
            f"{stage.name} ({stage.domain.upper()})",
        )
        self._update_action_states()
        self._refresh_navigation()

        def task():
            try:
                return True, self.controller.analyze(
                    analyzer,
                    image,
                    metadata,
                    roi=roi,
                    generation=generation,
                    cancel_token=token,
                    **options,
                )
            except Exception as exc:
                return False, exc

        self.workspace._run_async(
            f"Analyze {self.module_var.get()}",
            task,
            self._analysis_finished,
        )
        return True

    def _analysis_request(self):
        module = self.module_var.get()
        method = self.method_var.get()
        advanced = self._option_values()
        if module == "BLC":
            image_source = "Current RAW"
            options = dict(advanced)
            if method == "External Dark Frame":
                if not self.dark_frames:
                    raise ISPError("请先加载至少一张暗场图")
                # Controller gets the selected source in analyze(); the stage is
                # replaced in analyze request via a tiny source adapter option.
                options["override_image"] = self.dark_frames[0]
                options["_force_full"] = True
                image_source = (
                    self.dark_frame_paths[0]
                    if self.dark_frame_paths else "External Dark Frame"
                )
            elif method in {"Current Dark ROI", "Optical Black ROI"}:
                if self.app.roi is None:
                    raise ISPError(f"{method} 模式需要先在主界面选择 ROI")
                image_source = method
                options["_force_roi"] = True
            else:
                options["_force_full"] = True
            options["source_description"] = image_source
            return BLCAnalyzer(), 0, options
        if module == "LSC":
            rows = int(advanced.pop(
                "rows", self.workspace.mesh_rows_var.get()
            ))
            cols = int(advanced.pop(
                "cols", self.workspace.mesh_cols_var.get()
            ))
            self.workspace.mesh_rows_var.set(rows)
            self.workspace.mesh_cols_var.set(cols)
            return LSCAnalyzerAdapter(), self._stage_before(
                "lens_shading_correction"
            ), {
                "rows": rows,
                "cols": cols,
                "statistic": method,
                **advanced,
            }
        if module == "AWB":
            use_roi = (
                self.awb_region_var.get() == "Current ROI"
                or method == "ROI Neutral"
            )
            if use_roi and self.app.roi is None:
                raise ISPError(
                    "当前 AWB 模式需要 ROI。请先在主预览框选中性灰或白色区域。"
                )
            self.use_roi_var.set(use_roi)
            source = (
                "LSC output · Current neutral ROI"
                if use_roi else "LSC output · Full image"
            )
            options = {
                "method": method,
                "source_description": source,
                **advanced,
            }
            if use_roi:
                options["_force_roi"] = True
            else:
                options["_force_full"] = True
            return AWBAnalyzerAdapter(), self._stage_before(
                "white_balance"
            ), options
        if module == "AE":
            return AEAnalyzerAdapter(), self._stage_before(
                "white_balance"
            ), {
                "method": method,
                "domain": "bayer",
                **advanced,
            }
        if module == "CCM":
            rotation = int(advanced.get(
                "rotation", self.workspace.ccm_rotation_var.get()
            ))
            flipped = bool(advanced.get(
                "flip", self.workspace.ccm_flip_var.get()
            ))
            include_offset = bool(advanced.get(
                "include_offset", self.workspace.ccm_offset_var.get()
            ))
            ridge = float(advanced.get(
                "ridge", self.workspace.ccm_ridge_var.get()
            ))
            excluded = str(advanced.get(
                "excluded_patches", self.workspace.ccm_exclude_var.get()
            ))
            self.workspace.ccm_rotation_var.set(rotation)
            self.workspace.ccm_flip_var.set(flipped)
            self.workspace.ccm_offset_var.set(include_offset)
            self.workspace.ccm_ridge_var.set(ridge)
            self.workspace.ccm_exclude_var.set(excluded)
            return CCMAnalyzerAdapter(), self._stage_before(
                "color_correction_matrix"
            ), {
                "patches": self._colorchecker_patches(),
                "include_offset": include_offset,
                "ridge": ridge,
            }
        raise ISPError(f"未知自动分析模块：{module}")

    def _colorchecker_patches(self):
        stage = self.workspace._full_stage(
            self._stage_before("color_correction_matrix")
        )
        rotation = int(self.workspace.ccm_rotation_var.get())
        flipped = bool(self.workspace.ccm_flip_var.get())
        if len(getattr(self.app, "rois", [])) == 24:
            polygons = [
                [
                    (roi.x, roi.y),
                    (roi.x2, roi.y),
                    (roi.x2, roi.y2),
                    (roi.x, roi.y2),
                ]
                for roi in self.app.rois
            ]
            self.app.calibration_polygons = polygons
        else:
            corners = self.workspace._parse_corners()
            columns, rows = (
                (4, 6) if rotation in {90, 270} else (6, 4)
            )
            polygons = generate_colorchecker_grid(
                corners, columns=columns, rows=rows
            )
        names, references = colorchecker_reference(
            illuminant=self.workspace.illuminant_var.get()
        )
        order = reorder_reference_indices(rotation, flipped)
        patches = sample_colorchecker(
            stage.image, polygons, references, names, reference_indices=order
        )
        excluded = {
            int(token)
            for token in self.workspace.ccm_exclude_var.get().replace("，", ",").split(",")
            if token.strip()
        }
        return [patch for patch in patches if patch.patch_id not in excluded]

    def _analysis_finished(self, payload) -> None:
        success, value = payload
        self.busy.hide()
        module_name = self.module_var.get()
        machine = self.states[module_name]
        direct_apply = (
            self.direct_apply_after_analysis == module_name
        )
        if direct_apply or not success:
            self.direct_apply_after_analysis = ""
        if not success:
            machine.fail(str(value))
            self.message.show(str(value), "error")
            self._update_action_states()
            self._refresh_navigation()
            self._sync_main_status()
            return
        result: ParameterRecommendation = value
        self.result = result
        if module_name == "CCM":
            self._show_ccm_result(
                result, self.analysis_base_image
            )
            if direct_apply and not bool(
                result.measurements.get("safe_to_apply", False)
            ):
                reasons = result.measurements.get(
                    "rejection_reasons", []
                )
                machine.fail(
                    "CCM 未通过安全检查"
                    + (
                        "：" + "；".join(map(str, reasons))
                        if reasons else ""
                    )
                )
                self.message.show(
                    "CCM 结果已保留供检查，但未写入参数。"
                    "请修正色卡区域、曝光或异常色块后重新计算。",
                    "warning",
                )
                self._update_action_states()
                self._refresh_navigation()
                self._sync_main_status()
                return
        machine.transition(CalibrationUIState.SUGGESTED)
        machine.parameter_snapshot = copy.deepcopy(result.current_parameters)
        self.message.show(
            f"参数计算完成 · Confidence {result.confidence * 100:.1f}%",
            "success",
        )
        self._update_noise_roi_results(result)
        self._update_action_states()
        self._refresh_navigation()
        self._sync_main_status()
        if direct_apply:
            self.preview()
            self.apply()
            if module_name == "AWB":
                gains = result.suggested_parameters
                region = (
                    "当前 ROI"
                    if result.roi is not None else "全图"
                )
                summary = (
                    f"AWB 已矫正并应用 · {region} · "
                    f"R {gains.get('r_gain', 1.0):.3f} / "
                    f"Gr {gains.get('gr_gain', 1.0):.3f} / "
                    f"Gb {gains.get('gb_gain', 1.0):.3f} / "
                    f"B {gains.get('b_gain', 1.0):.3f}"
                )
            else:
                summary = f"{module_name} 已矫正并应用"
            if module_name == "CCM":
                self.app.show_ccm_compare()
            self.message.show(
                f"{summary} · Confidence "
                f"{result.confidence * 100:.1f}%",
                "success",
            )
            return
        self.toast.show("自动分析完成", "success")

    def preview(self) -> None:
        machine = self.states[self.module_var.get()]
        if self.result is None or not machine.can_preview:
            return
        target = self.app.pipeline.module_by_id(self.result.target)
        if machine.mark_stale_if_changed(target.parameters):
            self.message.show(
                "目标模块参数已变化，Recommendation 已过期，请重新 Analyze。",
                "warning",
            )
            self._update_action_states()
            self._refresh_navigation()
            return
        try:
            self.controller.preview(self.result)
        except Exception as exc:
            messagebox.showerror("Preview", str(exc), parent=self)
            return
        machine.transition(CalibrationUIState.PREVIEWING)
        self.preview_banner.show(
            f"正在预览“{self.module_var.get()}”自动建议，参数尚未应用。"
            " 可点击 Apply 确认或 Revert 恢复。",
            "preview",
        )
        self._update_action_states()
        self._refresh_navigation()
        self._sync_main_status()

    def apply(self) -> None:
        machine = self.states[self.module_var.get()]
        if self.result is None or not machine.can_apply:
            return
        try:
            self.controller.session = self.app.calibration_session
            self.controller.apply(self.result)
            if self.result.module_id == "flat_field_lsc":
                module = self.app.pipeline.module_by_id("lens_shading_correction")
                if module.mesh is not None:
                    self.app.calibration_session.lsc_mesh = module.mesh.copy()
            if hasattr(self.app, "commit_module_parameters"):
                self.app.commit_module_parameters(self.result.target)
            if self.result.module_id == "auto_white_balance":
                values = self.result.suggested_parameters
                self.app.calibration_session.awb_result = AWBResult(
                    r_gain=float(values.get("r_gain", 1.0)),
                    gr_gain=float(values.get("gr_gain", 1.0)),
                    gb_gain=float(values.get("gb_gain", 1.0)),
                    b_gain=float(values.get("b_gain", 1.0)),
                    confidence=float(self.result.confidence),
                    method=str(self.result.method),
                    sample_count=int(
                        self.result.measurements.get(
                            "sample_count", 0
                        )
                    ),
                    diagnostics=dict(self.result.measurements),
                    artifacts=dict(self.result.artifacts),
                )
            if self.result.module_id == "colorchecker_ccm":
                measurements = self.result.measurements
                self.app.calibration_session.ccm_result = (
                    CCMCalibrationResult.from_dict({
                        "matrix": measurements.get("matrix"),
                        "offset": measurements.get(
                            "offset", [0, 0, 0]
                        ),
                        "method": measurements.get(
                            "method", self.result.method
                        ),
                        "condition_number": measurements.get(
                            "condition_number", 0.0
                        ),
                        "delta_e_before": measurements.get(
                            "delta_e_before", {}
                        ),
                        "delta_e_after": measurements.get(
                            "delta_e_after", {}
                        ),
                        "patches": measurements.get("patches", []),
                        "diagnostics": measurements.get(
                            "diagnostics", {}
                        ),
                    })
                )
        except Exception as exc:
            messagebox.showerror("Apply", str(exc), parent=self)
            return
        machine.transition(CalibrationUIState.APPLIED)
        machine.parameter_snapshot = copy.deepcopy(
            self.app.pipeline.module_by_id(self.result.target).parameters
        )
        self.preview_banner.hide()
        self.toast.show(f"{self.module_var.get()} 建议已应用", "success")
        self._update_action_states()
        self._refresh_navigation()
        self._sync_main_status()

    def revert(self) -> None:
        machine = self.states[self.module_var.get()]
        if not machine.can_revert:
            return
        self.controller.revert()
        machine.transition(CalibrationUIState.SUGGESTED)
        self.preview_banner.hide()
        self.toast.show("Preview 已恢复", "info")
        self._update_action_states()
        self._refresh_navigation()
        self._sync_main_status()

    def cancel_analysis(self) -> None:
        machine = self.states[self.module_var.get()]
        if machine.state != CalibrationUIState.RUNNING:
            return
        self.controller.cancel_analysis()
        if self.direct_apply_after_analysis == self.module_var.get():
            self.direct_apply_after_analysis = ""
        self.workspace.generation += 1
        if (
            self.workspace.current_future is not None
            and not self.workspace.current_future.done()
        ):
            self.workspace.current_future.cancel()
        machine.transition(CalibrationUIState.CANCELLED)
        self.busy.hide()
        self.workspace.status_var.set("Cancelled")
        self.message.show("分析已取消", "warning")
        self._update_action_states()
        self._refresh_navigation()
        self._sync_main_status()

    def _update_noise_roi_results(
        self, result: ParameterRecommendation
    ) -> None:
        if result.module_id != "noise_profile":
            return
        items = []
        for sample in result.measurements.get("accepted_rois", []):
            roi = ImageROI.from_dict(sample["roi"])
            channels = sample.get("channels", {})
            means = [value.get("mean", 0.0) for value in channels.values()]
            variances = [
                value.get("variance", 0.0) for value in channels.values()
            ]
            items.append(ROIItem(
                roi,
                float(np.mean(means)) if means else None,
                float(np.mean(variances)) if variances else None,
                float(sample.get("gradient", 0.0)),
                True,
                "",
            ))
        for sample in result.measurements.get("rejected_rois", []):
            items.append(ROIItem(
                ImageROI.from_dict(sample["roi"]),
                accepted=False,
                reason=str(sample.get("reason", "Rejected")),
            ))
        if items:
            self.roi_list.set_items(items)

    def export_result(self) -> None:
        if self.result is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        try:
            save_recommendation(path, self.result)
        except Exception as exc:
            messagebox.showerror("Export analysis", str(exc), parent=self)
            return
        self.toast.show("分析结果已导出", "success")
        self.state_var.set(f"Exported: {path}")

    def get_ui_state(self) -> Dict[str, object]:
        return {
            "selected_module": self.module_var.get(),
            "sections": dict(self.section_state),
            "options_scroll": (
                float(self.options_canvas.yview()[0])
                if self.options_canvas.yview() else 0.0
            ),
            "methods": dict(self.method_preferences),
            "awb_region": self.awb_region_var.get(),
            "module_states": {
                name: machine.state.value
                for name, machine in self.states.items()
                if machine.state
                not in {
                    CalibrationUIState.RUNNING,
                    CalibrationUIState.PREVIEWING,
                }
            },
        }

    def load_ui_state(self, state: Dict[str, object]) -> None:
        if not isinstance(state, dict):
            return
        sections = state.get("sections", {})
        if isinstance(sections, dict):
            for key, section in (
                ("basic", self.basic_section),
                ("data", self.data_section),
            ):
                if key in sections:
                    section.set_expanded(bool(sections[key]))
        try:
            scroll_position = min(
                1.0, max(0.0, float(state.get("options_scroll", 0.0)))
            )
            self.after_idle(
                lambda value=scroll_position:
                self.options_canvas.yview_moveto(value)
            )
        except (TypeError, ValueError, tk.TclError):
            pass
        stored_states = state.get("module_states", {})
        if isinstance(stored_states, dict):
            for name, value in stored_states.items():
                if name not in self.states or self._saved_result(name) is None:
                    continue
                try:
                    restored = CalibrationUIState(str(value))
                except ValueError:
                    continue
                if restored in {
                    CalibrationUIState.RUNNING,
                    CalibrationUIState.PREVIEWING,
                }:
                    restored = CalibrationUIState.SUGGESTED
                self.states[name].state = restored
        methods = state.get("methods", {})
        if isinstance(methods, dict):
            self.method_preferences = {
                str(name): str(method) for name, method in methods.items()
                if name in self.MODULES
            }
        awb_region = str(state.get("awb_region", "Full Image"))
        if awb_region in {"Full Image", "Current ROI"}:
            self.awb_region_var.set(awb_region)
            self.use_roi_var.set(awb_region == "Current ROI")
        selected = str(state.get("selected_module", "BLC"))
        self.select_module(selected if selected in self.MODULES else "BLC")

    def refresh_session(self) -> None:
        """Bind the embedded panel to the newly active image session."""
        self.controller.close()
        self.controller = AutoCalibrationController(
            self.app.pipeline,
            lambda: self.app.schedule_process(immediate=True),
            self.app.calibration_session,
        )
        self.states = {
            name: CalibrationStateMachine() for name in self.MODULES
        }
        self.result = None
        self.analysis_base_image = None
        self.direct_apply_after_analysis = ""
        self.preview_banner.hide()
        self.message.hide()
        self._module_changed()

    def close(self) -> None:
        self.busy.hide()
        self.toast.close()
        self.controller.close()
