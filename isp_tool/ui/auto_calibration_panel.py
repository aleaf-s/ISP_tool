from __future__ import annotations

import copy
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Sequence

import numpy as np

from ..auto_calibration import (
    AEAnalyzerAdapter,
    AWBAnalyzerAdapter,
    AutoCalibrationController,
    BLCAnalyzer,
    CCMAnalyzerAdapter,
    DPCAnalyzer,
    DPCCalibrator,
    LSCAnalyzerAdapter,
    NoiseProfiler,
    SharpenAnalyzer,
    ToneAnalyzer,
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
from ..models import ISPError, ImageROI, ParameterRecommendation
from ..raw_io import PLAIN_EXTENSIONS, load_image
from .calibration_state import CalibrationStateMachine, CalibrationUIState
from .recommendation_view import RecommendationView
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
    """Unified Analyze → Preview → Apply/Revert workspace."""

    MODULES = (
        "BLC",
        "DPC",
        "LSC",
        "AWB",
        "AE",
        "CCM",
        "Noise Profile",
        "Tone",
        "Sharpen",
    )
    RECOMMENDATION_IDS = {
        "BLC": ("auto_blc",),
        "DPC": ("dpc_calibration", "auto_dpc"),
        "LSC": ("flat_field_lsc",),
        "AWB": ("auto_white_balance",),
        "AE": ("auto_exposure",),
        "CCM": ("colorchecker_ccm",),
        "Noise Profile": ("noise_profile",),
        "Tone": ("auto_tone",),
        "Sharpen": ("auto_sharpen",),
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
            "basic": True, "data": True, "advanced": False
        }
        self.method_preferences: Dict[str, str] = {}
        self.toast = ToastManager(self)
        self._build()

    def _build(self) -> None:
        actions = ttk.Frame(self)
        self.action_bar = actions
        actions.pack(side="bottom", fill="x", pady=(7, 0))
        self.revert_button = ttk.Button(
            actions, text="Revert", command=self.revert
        )
        self.revert_button.pack(side="left")
        self.preview_button = ttk.Button(
            actions, text="Preview", command=self.preview
        )
        self.preview_button.pack(side="left", padx=4)
        self.apply_button = ttk.Button(
            actions, text="Apply", style="Primary.TButton", command=self.apply
        )
        self.apply_button.pack(side="left")
        export_menu = ActionMenu(actions, "Export")
        export_menu.add_command(
            "Analysis result…", self.export_result,
            enabled=lambda: self.result is not None,
        )
        export_menu.add_command(
            "All artifacts…",
            lambda: self.view.artifact_gallery.export_all(),
            enabled=lambda: bool(self.view.artifact_gallery.artifacts),
        )
        export_menu.add_command(
            "Current artifact…",
            lambda: self.view.artifact_gallery.export_current(),
            enabled=lambda: bool(self.view.artifact_gallery.selected),
        )
        export_menu.add_separator()
        export_menu.add_command(
            "Debug report…", self.workspace._export_report,
            enabled=lambda: self.result is not None,
        )
        self.export_menu = export_menu
        export_menu.pack(side="left", padx=(12, 0))
        self.state_var = tk.StringVar(value="Not analyzed")
        ttk.Label(
            actions, textvariable=self.state_var, style="Muted.TLabel"
        ).pack(side="right")

        self.preview_banner = InlineMessage(self)
        self.preview_banner.pack(side="bottom", fill="x", pady=(6, 0))
        self.preview_banner.hide()

        workflow_header = ttk.Frame(self)
        workflow_header.pack(fill="x", pady=(0, 7))
        ttk.Label(
            workflow_header, text="CALIBRATION", style="Title.TLabel"
        ).pack(side="left")
        ttk.Label(
            workflow_header, text="Module", style="Muted.TLabel"
        ).pack(side="left", padx=(18, 5))
        self.module_var = tk.StringVar(value="BLC")
        self.module_combo = ttk.Combobox(
            workflow_header,
            textvariable=self.module_var,
            values=self.MODULES,
            state="readonly",
            width=18,
        )
        self.module_combo.pack(side="left")
        self.module_combo.bind(
            "<<ComboboxSelected>>", self._module_combo_changed
        )
        self.workflow_var = tk.StringVar(
            value="1 Data  ›  2 Analyze  ›  3 Review  ›  4 Apply"
        )
        ttk.Label(
            workflow_header,
            textvariable=self.workflow_var,
            style="Muted.TLabel",
        ).pack(side="right")

        workspace = ttk.Panedwindow(self, orient="horizontal")
        self.workspace_paned = workspace
        workspace.pack(fill="both", expand=True)
        middle = ttk.Frame(workspace, width=410, padding=(4, 4))
        right = ttk.Frame(workspace, padding=(8, 4))
        workspace.add(middle, weight=0)
        workspace.add(right, weight=1)

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
            middle, text="1  DATA & OPTIONS", style="Title.TLabel"
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
            options_host, "Basic options", expanded=True,
            on_toggle=lambda value: self._section_changed("basic", value),
        )
        self.basic_section.pack(fill="x")
        basic = self.basic_section.body
        ttk.Label(basic, text="Method / Mode").pack(anchor="w")
        self.method_var = tk.StringVar()
        self.method_combo = ttk.Combobox(
            basic, textvariable=self.method_var,
            state="readonly", width=23,
        )
        self.method_combo.pack(fill="x", pady=(2, 5))
        self.method_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._options_changed()
        )
        self.use_roi_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            basic, text="Use current ROI", variable=self.use_roi_var,
            command=self._options_changed,
        ).pack(anchor="w")

        self.data_section = CollapsibleSection(
            options_host, "Data source and samples", expanded=True,
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
        dpc_menu = ActionMenu(files, "DPC Map")
        dpc_menu.add_command("Import…", self._import_dpc_map)
        dpc_menu.add_command(
            "Export…", self._export_dpc_map,
            enabled=lambda: self.result is not None
            and self.module_var.get() == "DPC",
        )
        dpc_menu.pack(side="left", padx=5)
        manage_menu = ActionMenu(files, "Manage")
        manage_menu.add_command("Add noise ROI", self._add_noise_roi)
        manage_menu.add_command(
            "Analyze selected ROI", self._analyze_selected_noise_roi,
            enabled=lambda: bool(self.roi_list.tree.selection())
            if hasattr(self, "roi_list") else False,
        )
        manage_menu.add_command(
            "Analyze all ROIs", self._analyze_all_noise_rois,
            enabled=lambda: bool(self.noise_rois),
        )
        manage_menu.add_separator()
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
        manage_menu.add_command(
            "Remove selected ROI", self._remove_noise_roi,
            enabled=lambda: bool(self.roi_list.tree.selection())
            if hasattr(self, "roi_list") else False,
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
        manage_menu.add_command(
            "Clear noise ROIs", self._clear_noise_rois,
            enabled=lambda: bool(self.noise_rois),
        )
        manage_menu.pack(side="left")
        self.frame_status_var = tk.StringVar(
            value="Dark 0 · Flat 0 · Noise ROI 0"
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
        self.roi_list = ROIList(data, self._select_noise_roi)
        self.roi_list.pack(fill="x", pady=(3, 0))
        self.roi_list.configure_actions(
            self._remove_noise_roi,
            self._clear_noise_rois,
            self._analyze_selected_noise_roi,
        )

        self.advanced_section = CollapsibleSection(
            options_host, "Advanced options", expanded=False,
            on_toggle=lambda value: self._section_changed("advanced", value),
        )
        self.advanced_section.pack(fill="x", pady=(6, 0))
        self.advanced = self.advanced_section.body

        ttk.Label(
            right, text="3  REVIEW & APPLY", style="Title.TLabel"
        ).pack(anchor="w", pady=(0, 4))
        self.view = RecommendationView(right)
        self.view.pack(fill="both", expand=True)
        router = getattr(self.app, "wheel_router", None)
        if router is not None:
            for widget in (
                self.module_list,
                self.options_canvas,
                self.dark_file_list.tree,
                self.flat_file_list.tree,
                self.roi_list.tree,
                self.view.parameter_diff.tree,
                self.view.measurements,
                self.view.warnings,
            ):
                router.register(widget, widget)
            router.register(
                self.view.artifact_gallery.thumbnail_canvas,
                self.view.artifact_gallery.thumbnail_canvas,
                axis="x",
            )
        self._module_changed()
        self._refresh_navigation()
        self._update_action_states()

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
            "DPC": ("Single Frame", "Multi-frame Calibration"),
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
            "Noise Profile": ("Mean-Variance Model",),
            "Tone": ToneAnalyzer.MODES,
            "Sharpen": ("Edge and Noise Heuristic",),
        }
        choices = tuple(values[self.module_var.get()])
        self.method_combo.configure(values=choices)
        preferred = self.method_preferences.get(self.module_var.get(), choices[0])
        self.method_var.set(preferred if preferred in choices else choices[0])
        self._build_advanced_options()
        result = self._saved_result(self.module_var.get())
        self.result = result
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
            self.view.set_result(result, self.analysis_base_image)
        else:
            self.view.clear()
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

    def _module_combo_changed(self, _event=None) -> None:
        requested = self.module_var.get()
        selection = self.module_list.curselection()
        previous = (
            self.MODULES[int(selection[0])]
            if selection else requested
        )
        self.module_var.set(previous)
        self.select_module(requested)

    def select_module(self, name: str) -> None:
        if name not in self.MODULES:
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
        if not self.app.results:
            self.source_var.set("Stage: waiting for preview")
            return
        try:
            index = {
                "BLC": 0, "DPC": 1, "LSC": 1, "AWB": 3, "AE": 3,
                "CCM": 5, "Noise Profile": 7, "Tone": 6, "Sharpen": 8,
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

    def _update_action_states(self) -> None:
        machine = self.states[self.module_var.get()]
        self.analyze_button.configure(
            state="normal" if machine.can_analyze else "disabled"
        )
        self.preview_button.configure(
            state=(
                "normal"
                if self.result is not None and machine.can_preview
                else "disabled"
            )
        )
        self.apply_button.configure(
            state=(
                "normal"
                if self.result is not None and machine.can_apply
                else "disabled"
            )
        )
        self.revert_button.configure(
            state="normal" if machine.can_revert else "disabled"
        )
        for button in (
            self.preview_button,
            self.apply_button,
            self.revert_button,
        ):
            button.pack_forget()
        state = machine.state
        if state == CalibrationUIState.SUGGESTED:
            self.preview_button.pack(
                side="left", before=self.export_menu
            )
        elif state == CalibrationUIState.PREVIEWING:
            self.apply_button.pack(
                side="left", before=self.export_menu
            )
            self.revert_button.pack(
                side="left", padx=4, before=self.export_menu
            )
        workflow = {
            CalibrationUIState.NOT_ANALYZED:
                "1 Data  ●  2 Analyze  ○  3 Review  ○  4 Apply",
            CalibrationUIState.RUNNING:
                "1 Data  ✓  2 Analyzing…  ●  3 Review  ○  4 Apply",
            CalibrationUIState.SUGGESTED:
                "1 Data  ✓  2 Analyze  ✓  3 Review  ●  4 Apply",
            CalibrationUIState.PREVIEWING:
                "1 Data  ✓  2 Analyze  ✓  3 Review  ✓  4 Apply  ●",
            CalibrationUIState.APPLIED:
                "1 Data  ✓  2 Analyze  ✓  3 Review  ✓  4 Applied  ✓",
            CalibrationUIState.STALE:
                "Parameters changed · Re-analyze required",
            CalibrationUIState.FAILED:
                "Analysis failed · Adjust data and retry",
            CalibrationUIState.CANCELLED:
                "Analysis cancelled · Ready to retry",
        }
        self.workflow_var.set(workflow[state])
        self.state_var.set(machine.state.value.replace("_", " ").title())
        self.view.set_state(machine.state)

    def _sync_main_status(self) -> None:
        self.app._refresh_pipeline_list()
        self.app._refresh_auto_summary()
        module = self.app.pipeline.modules[
            self.app.selected_module_index
        ]
        self.app._build_parameter_editor(module)
        self.app._refresh_module_state()

    def _build_advanced_options(self) -> None:
        for child in self.advanced.winfo_children():
            child.destroy()
        self.option_vars = {}
        module = self.module_var.get()
        specifications = {
            "BLC": (
                ("Statistic", "statistic", "choice", "Median", ("Median", "Trimmed Mean", "Mean")),
                ("Trim fraction", "trim_fraction", "float", 0.05, ()),
            ),
            "DPC": (
                ("Persistence", "persistence_threshold", "float", 0.8, ()),
                ("Sigma threshold", "sigma_threshold", "float", 7.0, ()),
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
            "Noise Profile": (
                ("Grid rows", "grid_rows", "int", 4, ()),
                ("Grid cols", "grid_cols", "int", 4, ()),
                ("Texture threshold", "texture_threshold", "float", 0.12, ()),
            ),
            "Tone": (
                ("Max clipping", "maximum_allowed_clipping", "float", 0.01, ()),
            ),
            "Sharpen": (),
        }[module]
        if not specifications:
            ttk.Label(
                self.advanced,
                text="This analyzer uses the specialist controls or measured image content.",
                style="Muted.TLabel",
            ).pack(side="left")
            return
        self.advanced.columnconfigure(1, weight=1)
        for row, (label, key, kind, default, choices) in enumerate(
            specifications
        ):
            ttk.Label(self.advanced, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 6), pady=2
            )
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
            if kind == "choice":
                widget = ttk.Combobox(
                    self.advanced, textvariable=variable,
                    values=choices, state="readonly", width=13,
                )
            elif kind == "bool":
                widget = ttk.Checkbutton(
                    self.advanced, variable=variable
                )
            else:
                widget = ttk.Entry(
                    self.advanced, textvariable=variable, width=13
                )
            widget.grid(row=row, column=1, sticky="ew", pady=2)
        if module == "CCM":
            actions = ttk.Frame(self.advanced)
            actions.grid(
                row=len(specifications), column=0, columnspan=2,
                sticky="ew", pady=(5, 0),
            )
            ttk.Button(
                actions, text="Use Current ROI",
                command=self._ccm_corners_from_roi,
            ).pack(side="left")
            ttk.Button(
                actions, text="Edit Corners",
                command=self.workspace._edit_colorchecker_corners,
            ).pack(side="left", padx=4)

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
                        frame, loaded.metadata.bayer_pattern, max_side=1500
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
            f"Dark {len(self.dark_frames)} · Flat {len(self.flat_frames)} · "
            f"Noise ROI {len(self.noise_rois)}"
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

    def analyze(self) -> None:
        if self.controller.has_preview:
            self.controller.revert()
            machine = self.states[self.module_var.get()]
            if machine.state == CalibrationUIState.PREVIEWING:
                machine.transition(CalibrationUIState.SUGGESTED)
            self.preview_banner.hide()
            self.toast.show("Preview 已恢复，请在主预览刷新后重新 Analyze", "info")
            self._update_action_states()
            return
        machine = self.states[self.module_var.get()]
        if not machine.can_analyze:
            return
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
            return
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
        if module == "DPC":
            if method == "Multi-frame Calibration":
                if len(self.dark_frames) + len(self.flat_frames) < 2:
                    raise ISPError("多帧 DPC 至少需要两张暗场或平场")
                return DPCCalibrator(), 1, {
                    "dark_frames": self.dark_frames,
                    "flat_frames": self.flat_frames,
                    "source_description": (
                        f"{len(self.dark_frames)} dark + "
                        f"{len(self.flat_frames)} flat frames"
                    ),
                    **advanced,
                }
            return DPCAnalyzer(), 1, advanced
        if module == "LSC":
            rows = int(advanced.pop(
                "rows", self.workspace.mesh_rows_var.get()
            ))
            cols = int(advanced.pop(
                "cols", self.workspace.mesh_cols_var.get()
            ))
            self.workspace.mesh_rows_var.set(rows)
            self.workspace.mesh_cols_var.set(cols)
            return LSCAnalyzerAdapter(), 1, {
                "rows": rows,
                "cols": cols,
                "statistic": method,
                **advanced,
            }
        if module == "AWB":
            # AWB must measure LSC output before existing WB gains. Measuring
            # stage 3 would analyze an already white-balanced image and drift
            # toward unity on every re-analysis.
            return AWBAnalyzerAdapter(), 2, {"method": method, **advanced}
        if module == "AE":
            return AEAnalyzerAdapter(), 2, {
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
            return CCMAnalyzerAdapter(), 5, {
                "patches": self._colorchecker_patches(),
                "include_offset": include_offset,
                "ridge": ridge,
            }
        if module == "Noise Profile":
            rois = list(self.noise_rois)
            if self.noise_scope == "selected":
                selected = self.roi_list.tree.selection()
                if not selected:
                    raise ISPError("请先选择一个 Noise ROI")
                rois = [self.roi_list.items()[int(selected[0])].roi]
            return NoiseProfiler(), 7, {
                "domain": "rgb",
                "rois": rois or None,
                **advanced,
            }
        if module == "Tone":
            return ToneAnalyzer(), 6, {"mode": method, **advanced}
        if module == "Sharpen":
            return SharpenAnalyzer(), 8, {}
        raise ISPError(f"未知自动分析模块：{module}")

    def _colorchecker_patches(self):
        stage = self.workspace._full_stage(5)
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
        machine = self.states[self.module_var.get()]
        if not success:
            machine.fail(str(value))
            self.message.show(str(value), "error")
            self._update_action_states()
            self._refresh_navigation()
            self._sync_main_status()
            return
        result: ParameterRecommendation = value
        self.result = result
        machine.transition(CalibrationUIState.SUGGESTED)
        machine.parameter_snapshot = copy.deepcopy(result.current_parameters)
        self.view.set_result(result, self.analysis_base_image)
        self.message.show(
            f"分析完成 · Confidence {result.confidence * 100:.1f}% · "
            f"{len(result.warnings)} warning(s)",
            "success" if not result.warnings else "warning",
        )
        self.toast.show("自动分析完成", "success")
        self._update_noise_roi_results(result)
        self._update_action_states()
        self._refresh_navigation()
        self._sync_main_status()

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
        self.view.set_state(CalibrationUIState.PREVIEWING)
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
        except Exception as exc:
            messagebox.showerror("Apply", str(exc), parent=self)
            return
        machine.transition(CalibrationUIState.APPLIED)
        machine.parameter_snapshot = copy.deepcopy(
            self.app.pipeline.module_by_id(self.result.target).parameters
        )
        self.preview_banner.hide()
        self.view.set_result(self.result, self.analysis_base_image)
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
            "artifact_mode": self.view.artifact_gallery.mode_var.get(),
            "artifact_opacity": float(
                self.view.artifact_gallery.opacity_var.get()
            ),
            "artifact_fit": bool(self.view.artifact_gallery.fit),
            "options_scroll": (
                float(self.options_canvas.yview()[0])
                if self.options_canvas.yview() else 0.0
            ),
            "methods": dict(self.method_preferences),
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
                ("advanced", self.advanced_section),
            ):
                if key in sections:
                    section.set_expanded(bool(sections[key]))
        mode = str(state.get("artifact_mode", "Artifact"))
        if mode in self.view.artifact_gallery.MODES:
            self.view.artifact_gallery.mode_var.set(mode)
        try:
            self.view.artifact_gallery.opacity_var.set(
                min(1.0, max(0.0, float(state.get("artifact_opacity", 0.65))))
            )
        except (TypeError, ValueError, tk.TclError):
            pass
        self.view.artifact_gallery.fit = bool(state.get("artifact_fit", True))
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
        selected = str(state.get("selected_module", "BLC"))
        self.select_module(selected if selected in self.MODULES else "BLC")

    def close(self) -> None:
        self.busy.hide()
        self.toast.close()
        self.controller.close()
