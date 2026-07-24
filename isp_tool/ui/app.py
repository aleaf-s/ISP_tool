from __future__ import annotations

import copy
import json
import math
import re
import time
import traceback
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageTk

from ..bayer import resize_bayer_preview
from ..calibration.awb import estimate_awb
from ..analysis import (
    compute_histogram,
    compute_statistics,
    compute_vectorscope,
    compute_waveform,
)
from ..config import load_config, save_config
from ..models import (
    CalibrationSession,
    ISPError,
    ImageROI,
    LoadedImage,
    RawMetadata,
    StageResult,
)
from ..modules.tone import evaluate_tone_curve
from ..pipeline import ISPPipeline
from ..preview import artifact_to_rgb, display_rgb, export_image
from ..raw_io import PLAIN_EXTENSIONS, load_image, synthetic_bayer
from ..roi_tools import clamp_roi, generate_grid_rois
from ..workspace import (
    ImageWorkItem,
    compatible_for_transfer,
    snapshot_for_image,
    transfer_module_settings,
)
from .calibration_panel import CalibrationWorkspace
from .dialogs import ask_raw_metadata
from .dpi import enable_process_dpi_awareness
from .performance_metrics import PerformanceMetrics
from .render_cache import RenderCache
from .roi_editor import ROIEditor
from .scrolling import MouseWheelRouter
from .theme import COLORS, FONTS, UI_SCALE_CHOICES, configure_theme
from .widgets import ActionMenu, InlineMessage, StatusBadge, ToastManager


APP_TITLE = "ISP RAW Visual Simulator V0.4.4 · 多图校准工作区"
BG = COLORS["background"]
PANEL = COLORS["panel"]
PANEL_2 = COLORS["panel_alt"]
FG = COLORS["foreground"]
MUTED = COLORS["muted"]
ACCENT = COLORS["accent"]
GREEN = COLORS["success"]
RED = COLORS["error"]
AUTO_RECOMMENDATION_IDS = {
    "BLC": ("auto_blc",),
    "DPC": ("dpc_calibration", "auto_dpc"),
    "LSC": ("flat_field_lsc",),
    "AWB": ("auto_white_balance",),
    "CCM": ("colorchecker_ccm",),
    "Noise Profile": ("noise_profile",),
    "Tone": ("auto_tone",),
    "Sharpen": ("auto_sharpen",),
}
BASIC_PARAMETER_KEYS = {
    "black_level_correction": {
        "r", "gr", "gb", "b", "global_offset",
    },
    "defective_pixel_correction": {
        "mode", "threshold", "neighborhood",
    },
    "lens_shading_correction": {
        "mode", "r_strength", "gr_strength", "gb_strength", "b_strength",
    },
    "white_balance": {
        "r_gain", "gr_gain", "gb_gain", "b_gain", "exposure_gain",
    },
    "demosaic": {
        "algorithm", "false_color_suppression",
    },
    "color_correction_matrix": {
        "m00", "m01", "m02", "m10", "m11",
        "m12", "m20", "m21", "m22", "strength",
    },
    "tone_mapping": {
        "gamma", "black_point", "white_point", "contrast",
    },
    "noise_reduction": {
        "algorithm", "spatial_strength", "chroma_strength",
        "edge_protection",
    },
    "sharpen": {
        "strength", "radius", "threshold", "halo_suppression",
    },
    "color_adjustment": {
        "brightness", "contrast", "saturation", "hue",
    },
}


class ISPApplication:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1320x740")
        self.root.minsize(1040, 650)
        self.root.configure(bg=BG)
        self.ui_scale = 1.0
        self.ui_scale_var = tk.StringVar(value="100%")
        self.performance_details_visible = False
        self.performance_window: Optional[tk.Toplevel] = None
        self.performance_text: Optional[tk.Text] = None
        self.pipeline = ISPPipeline()
        self.loaded: LoadedImage = synthetic_bayer()
        self.calibration_session = CalibrationSession(
            name="Untitled Calibration",
            raw_metadata=copy.deepcopy(self.loaded.metadata),
        )
        self.work_items: List[ImageWorkItem] = [
            ImageWorkItem(
                self.loaded,
                copy.deepcopy(self.pipeline.snapshot()),
                copy.deepcopy(self.calibration_session),
            )
        ]
        self.current_image_index = 0
        self.calibration_workspace: Optional[CalibrationWorkspace] = None
        self.calibration_polygons = []
        self.preview_image = self.loaded.image
        self.results: List[StageResult] = []
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="isp-preview")
        self.analysis_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="isp-analysis"
        )
        self.io_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="isp-import"
        )
        self.current_future: Optional[Future] = None
        self.analysis_future: Optional[Future] = None
        self.import_future: Optional[Future] = None
        self.import_generation = 0
        self.import_poll_after: Optional[str] = None
        self.pipeline_cache: Dict[str, object] = {}
        self.render_cache = RenderCache()
        self.performance = PerformanceMetrics()
        self.input_revision = 0
        self.result_revision = 0
        self.generation = 0
        self.analysis_generation = 0
        self.pending_after: Optional[str] = None
        self.analysis_pending_after: Optional[str] = None
        self.canvas_resize_after: Optional[str] = None
        self.canvas_overlay_after: Optional[str] = None
        self.view_render_after: Optional[str] = None
        self.poll_after_ids: set[str] = set()
        self.analysis_poll_after_ids: set[str] = set()
        self.photo: Optional[ImageTk.PhotoImage] = None
        self.waveform_photo: Optional[ImageTk.PhotoImage] = None
        self.vectorscope_photo: Optional[ImageTk.PhotoImage] = None
        self.display_array: Optional[np.ndarray] = None
        self._display_revision = 0
        self._raster_key = None
        self._raster_photo: Optional[ImageTk.PhotoImage] = None
        self._last_analysis_payload = None
        self._last_mouse_status_at = 0.0
        self.display_transform = (0.0, 0.0, 1.0, 0, 0)
        self.zoom = 1.0
        self.fit_mode = True
        self.pan_start: Optional[Tuple[int, int]] = None
        self.canvas_origin = [0.0, 0.0]
        self.gray_pick_mode = False
        self.rois: List[ImageROI] = []
        self.roi: Optional[ImageROI] = None
        self.active_roi_index = -1
        self.roi_drag_start: Optional[Tuple[int, int]] = None
        self.roi_drag_original: Optional[ImageROI] = None
        self.roi_drag_mode = ""
        self.roi_resize_handle = ""
        self.roi_editor: Optional[ROIEditor] = None
        self.compare_position = 0.5
        self.compare_dragging = False
        self.temporary_input = False
        self.param_vars: Dict[str, tk.Variable] = {}
        self.manual_parameter_snapshots: Dict[str, Dict[str, object]] = {}
        self.manual_dirty_modules: set[str] = set()
        self.advanced_param_state: Dict[str, bool] = {}
        self.advanced_params_frame: Optional[ttk.Frame] = None
        self.advanced_params_button: Optional[ttk.Button] = None
        self.tone_curve_canvas: Optional[tk.Canvas] = None
        self.ccm_info_label: Optional[ttk.Label] = None
        self.pending_artifact: Optional[str] = None
        self.selected_module_index = 0
        self.loaded_ui_state: Dict[str, object] = {}
        self.last_directory = ""
        self.analysis_collapsed = True
        self.expert_mode = False
        self.wheel_router = MouseWheelRouter(self.root)
        self._configure_style()
        self.toast = ToastManager(self.root)
        self._build_menu()
        self._build_layout()
        self.wheel_router.register(self.pipeline_list, self.pipeline_list)
        self.wheel_router.register(self.param_canvas, self.param_canvas)
        self._sync_blc_to_metadata()
        self._reset_manual_parameter_snapshots()
        self._store_current_work_item()
        self._refresh_pipeline_list()
        self.pipeline_list.selection_set(0)
        self._on_module_select()
        self._set_loaded_status()
        self.schedule_process(immediate=True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_style(self) -> None:
        configure_theme(self.root, self.ui_scale)

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        file_menu = tk.Menu(menu, tearoff=False, bg=PANEL_2, fg=FG)
        file_menu.add_command(
            label="导入一张或多张图像 / RAW…    Ctrl+O",
            command=self.open_files,
        )
        file_menu.add_command(label="裸 RAW 元数据…", command=self.edit_raw_metadata)
        file_menu.add_separator()
        file_menu.add_command(label="加载 ISP 配置…", command=self.load_pipeline_config)
        file_menu.add_command(label="保存 ISP 配置…    Ctrl+S", command=self.save_pipeline_config)
        file_menu.add_separator()
        file_menu.add_command(label="导出当前结果…    Ctrl+E", command=self.export_current)
        file_menu.add_command(label="导出 ROI…", command=self.export_roi)
        file_menu.add_command(label="退出", command=self.close)
        menu.add_cascade(label="文件", menu=file_menu)
        view_menu = tk.Menu(menu, tearoff=False, bg=PANEL_2, fg=FG)
        view_menu.add_command(label="适合窗口    F", command=self.fit_image)
        view_menu.add_command(label="1:1 像素    1", command=self.actual_size)
        view_menu.add_command(label="重置当前模块", command=self.reset_current_module)
        view_menu.add_command(
            label="Calibration Workspace", command=self.open_calibration_workspace
        )
        view_menu.add_command(
            label="Performance Details", command=self.show_performance_details
        )
        scale_menu = tk.Menu(view_menu, tearoff=False, bg=PANEL_2, fg=FG)
        for label in UI_SCALE_CHOICES:
            scale_menu.add_radiobutton(
                label=label,
                variable=self.ui_scale_var,
                value=label,
                command=self._apply_ui_scale_from_menu,
            )
        view_menu.add_cascade(label="UI Scale", menu=scale_menu)
        menu.add_cascade(label="视图", menu=view_menu)
        help_menu = tk.Menu(menu, tearoff=False, bg=PANEL_2, fg=FG)
        help_menu.add_command(label="关于", command=self.show_about)
        menu.add_cascade(label="帮助", menu=help_menu)
        self.root.config(menu=menu)
        self.root.bind(
            "<Control-o>",
            lambda event: self._shortcut(event, self.open_files, False),
        )
        self.root.bind(
            "<Control-s>",
            lambda event: self._shortcut(
                event, self.save_pipeline_config, False
            ),
        )
        self.root.bind(
            "<Control-e>",
            lambda event: self._shortcut(event, self.export_current, False),
        )
        self.root.bind(
            "<Control-Shift-C>",
            lambda event: self._shortcut(
                event, self.open_calibration_workspace, False
            ),
        )
        self.root.bind("<Key-f>", lambda event: self._shortcut(event, self.fit_image))
        self.root.bind("<Key-1>", lambda event: self._shortcut(event, self.actual_size))
        self.root.bind(
            "<Key-r>",
            lambda event: self._shortcut(event, self.toggle_roi_mode),
        )
        self.root.bind(
            "<Key-a>",
            lambda event: self._shortcut(event, self.analyze_current_module),
        )
        self.root.bind(
            "<Key-p>",
            lambda event: self._shortcut(event, self.preview_auto_suggestion),
        )
        self.root.bind(
            "<Return>",
            lambda event: self._shortcut(event, self.apply_auto_suggestion),
        )
        self.root.bind(
            "<Escape>",
            lambda event: self._shortcut(event, self.revert_or_cancel_auto),
        )
        self.root.bind("<KeyPress-space>", self._show_temporary_input)
        self.root.bind("<KeyRelease-space>", self._hide_temporary_input)
        for key, dx, dy in (
            ("Left", -1, 0),
            ("Right", 1, 0),
            ("Up", 0, -1),
            ("Down", 0, 1),
        ):
            self.root.bind(
                f"<{key}>",
                lambda event, x=dx, y=dy:
                self._nudge_active_roi(event, x, y),
            )

    def _build_layout(self) -> None:
        self.compare_var = tk.BooleanVar(value=False)
        self.clipping_var = tk.BooleanVar(value=False)
        self.artifact_var = tk.StringVar(value="Main Output")
        self.artifact_overlay_var = tk.BooleanVar(value=False)
        self.roi_mode_var = tk.BooleanVar(value=False)
        self.roi_process_var = tk.BooleanVar(value=False)
        self.channel_var = tk.StringVar(value="RGB")
        self.analysis_panel_collapsed_var = tk.BooleanVar(
            value=self.analysis_collapsed
        )
        self.expert_mode_var = tk.BooleanVar(value=self.expert_mode)

        toolbar = ttk.Frame(self.root, padding=(8, 7))
        toolbar.pack(fill="x")
        ttk.Button(
            toolbar, text="导入图像", style="Accent.TButton",
            command=self.open_files,
        ).pack(side="left")
        self.image_var = tk.StringVar()
        self.image_combo = ttk.Combobox(
            toolbar,
            textvariable=self.image_var,
            state="readonly",
            width=23,
        )
        self.image_combo.pack(side="left", padx=(5, 8))
        self.image_combo.bind(
            "<<ComboboxSelected>>", self._on_image_selected
        )
        self._refresh_image_selector()
        ttk.Button(
            toolbar, text="保存参数", command=self.save_pipeline_config
        ).pack(side="left", padx=5)
        export_menu = ActionMenu(toolbar, "导出")
        export_menu.add_command(
            "当前模块输出…", self.export_main_output,
            enabled=lambda: bool(self.results),
        )
        export_menu.add_command(
            "当前 ROI…", self.export_roi,
            enabled=lambda: bool(self.results and self.roi),
        )
        export_menu.add_command(
            "当前 Artifact…", self.export_current,
            enabled=lambda: bool(
                self.results and self.artifact_var.get() != "Main Output"
            ),
        )
        export_menu.add_separator()
        export_menu.add_command("ISP 参数配置…", self.save_pipeline_config)
        export_menu.pack(side="left")
        ttk.Button(
            toolbar, text="Calibration", command=self.open_calibration_workspace
        ).pack(side="left", padx=(5, 0))
        ttk.Button(
            toolbar, text="Scope", command=self._toggle_analysis_panel
        ).pack(side="left", padx=(5, 0))
        view_menu = ActionMenu(toolbar, "视图")
        view_menu.add_checkbutton(
            "专家模式", self.expert_mode_var,
            command=self._apply_expert_mode,
        )
        view_menu.add_separator()
        view_menu.add_command("Performance Details", self.show_performance_details)
        view_menu.pack(side="left", padx=(5, 0))
        self.stage_selector = ttk.Frame(toolbar)
        ttk.Separator(
            self.stage_selector, orient="vertical"
        ).pack(side="left", fill="y", padx=10)
        ttk.Label(self.stage_selector, text="查看阶段：").pack(side="left")
        self.stage_var = tk.StringVar()
        self.stage_combo = ttk.Combobox(
            self.stage_selector,
            textvariable=self.stage_var,
            state="readonly",
            width=28,
        )
        self.stage_combo.pack(side="left")
        self.stage_combo.bind("<<ComboboxSelected>>", self._on_stage_changed)
        # Compatibility combobox remains the single source for values used by
        # older integrations, but the visible control is the compact Display menu.
        self.artifact_combo = ttk.Combobox(
            toolbar,
            textvariable=self.artifact_var,
            values=("Main Output",),
            state="readonly",
            width=1,
        )

        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True)
        self.main_paned = main
        left = ttk.Frame(main, width=220, padding=(10, 8))
        center = ttk.Frame(main, style="Dark.TFrame")
        right = ttk.Frame(main, width=335, padding=(10, 8))
        main.add(left, weight=0)
        main.add(center, weight=1)
        main.add(right, weight=0)

        ttk.Label(left, text="ISP PIPELINE", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        self.pipeline_list = tk.Listbox(
            left, bg=PANEL_2, fg=FG,
            selectbackground=COLORS["selection"], selectforeground="white",
            relief="flat", highlightthickness=1,
            highlightbackground=COLORS["border"],
            font=FONTS["body"], activestyle="none", width=26,
        )
        self.pipeline_list.pack(fill="both", expand=True)
        self.pipeline_list.bind("<<ListboxSelect>>", lambda _event: self._on_module_select())
        self.enabled_var = tk.BooleanVar(value=True)

        self.image_canvas = tk.Canvas(
            center, bg=COLORS["canvas"], highlightthickness=0,
            cursor="crosshair",
        )
        self.image_canvas.bind("<Configure>", lambda _event: self._on_canvas_resize())
        self.image_canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.image_canvas.bind("<Button-4>", lambda event: self._zoom_at(event.x, event.y, 1.15))
        self.image_canvas.bind("<Button-5>", lambda event: self._zoom_at(event.x, event.y, 1 / 1.15))
        self.image_canvas.bind("<ButtonPress-2>", self._start_pan)
        self.image_canvas.bind("<B2-Motion>", self._pan)
        self.image_canvas.bind("<ButtonPress-3>", self._start_pan)
        self.image_canvas.bind("<B3-Motion>", self._pan)
        self.image_canvas.bind("<Motion>", self._on_canvas_motion)
        self.image_canvas.bind("<ButtonPress-1>", self._on_left_press)
        self.image_canvas.bind("<B1-Motion>", self._on_left_drag)
        self.image_canvas.bind("<ButtonRelease-1>", self._on_left_release)

        canvas_toolbar = ttk.Frame(center, padding=(8, 5))
        canvas_toolbar.pack(fill="x")
        ttk.Button(canvas_toolbar, text="适合窗口", command=self.fit_image).pack(side="left")
        ttk.Button(canvas_toolbar, text="1:1", command=self.actual_size).pack(side="left", padx=5)
        self.zoom_label = ttk.Label(canvas_toolbar, text="100%", style="Muted.TLabel")
        self.zoom_label.pack(side="left")
        ttk.Separator(
            canvas_toolbar, orient="vertical"
        ).pack(side="left", fill="y", padx=6)
        roi_menu = ActionMenu(canvas_toolbar, "ROI")
        roi_menu.add_checkbutton(
            "选择 ROI", self.roi_mode_var, command=self._roi_mode_changed
        )
        roi_menu.add_checkbutton(
            "仅处理 ROI", self.roi_process_var,
            command=self._roi_processing_changed,
        )
        roi_menu.add_command(
            "生成 4×6 色块 ROI", self.generate_24_rois,
            enabled=lambda: self.roi is not None,
        )
        roi_menu.add_command(
            "生成 6×4 色块 ROI（旋转色卡）",
            lambda: self.generate_24_rois(rows=6, cols=4),
            enabled=lambda: self.roi is not None,
        )
        roi_menu.add_command(
            "ROI 管理与微调…", self.open_roi_editor
        )
        roi_menu.add_separator()
        roi_menu.add_command(
            "删除当前 ROI", self.delete_active_roi,
            enabled=lambda: self.roi is not None,
        )
        roi_menu.add_command(
            "清除全部 ROI", self.clear_roi,
            enabled=lambda: bool(self.rois),
        )
        roi_menu.add_command(
            "导出 ROI…", self.export_roi,
            enabled=lambda: self.roi is not None and bool(self.results),
        )
        roi_menu.pack(side="left")
        ttk.Button(
            canvas_toolbar, text="Gray", command=self.arm_gray_picker
        ).pack(side="left", padx=3)
        ttk.Checkbutton(
            canvas_toolbar, text="Compare", variable=self.compare_var,
            command=lambda: self.render_current(schedule_analysis=False),
        ).pack(side="left")
        self.display_menu = ActionMenu(canvas_toolbar, "Display")
        for channel in ("RGB", "R", "G", "B", "Luma"):
            self.display_menu.add_radiobutton(
                channel, self.channel_var, channel,
                command=lambda: self.render_current(schedule_analysis=True),
            )
        self.display_menu.add_separator()
        self.display_menu.add_checkbutton(
            "过/欠曝提示", self.clipping_var,
            command=lambda: self.render_current(schedule_analysis=True),
        )
        self.display_menu.add_checkbutton(
            "叠加 Artifact", self.artifact_overlay_var,
            command=lambda: self.render_current(schedule_analysis=False),
        )
        self.artifact_submenu = tk.Menu(self.display_menu.menu, tearoff=False)
        self.display_menu.add_cascade("Artifact", self.artifact_submenu)
        self.display_menu.pack(side="left", padx=3)
        self.roi_label = ttk.Label(
            canvas_toolbar, text="ROI: Full frame", style="Muted.TLabel"
        )
        self.roi_label.pack(side="right", padx=(8, 2))
        self.image_canvas.pack(fill="both", expand=True)

        ttk.Label(right, text="CURRENT MODULE", style="Muted.TLabel").pack(
            anchor="w"
        )
        self.module_title = ttk.Label(right, text="", style="Title.TLabel")
        self.module_title.pack(anchor="w", pady=(2, 2))
        self.module_state_var = tk.StringVar(value="Enabled")
        ttk.Label(
            right, textvariable=self.module_state_var, style="Muted.TLabel"
        ).pack(anchor="w")
        module_actions = ttk.Frame(right)
        module_actions.pack(fill="x", pady=(7, 8))
        ttk.Checkbutton(
            module_actions,
            text="Enable",
            variable=self.enabled_var,
            command=self._toggle_module,
        ).pack(side="left")
        self.module_brush_menu = ActionMenu(
            module_actions, "校准刷"
        )
        self.module_brush_menu.add_command(
            "当前模块 → 选择目标图像…",
            self.brush_current_module_to_selected,
            enabled=lambda: len(self.work_items) > 1,
        )
        self.module_brush_menu.add_command(
            "当前模块 → 其他全部图像",
            self.brush_current_module_to_all,
            enabled=lambda: len(self.work_items) > 1,
        )
        self.module_brush_menu.add_separator()
        self.module_brush_menu.add_command(
            "Sensor 校准组（BLC/DPC/LSC）→ 全部",
            lambda: self.apply_calibration_brush(
                (
                    "black_level_correction",
                    "defective_pixel_correction",
                    "lens_shading_correction",
                )
            ),
            enabled=lambda: len(self.work_items) > 1,
        )
        self.module_brush_menu.add_command(
            "颜色校准组（WB/CCM）→ 全部",
            lambda: self.apply_calibration_brush(
                ("white_balance", "color_correction_matrix")
            ),
            enabled=lambda: len(self.work_items) > 1,
        )
        self.module_brush_menu.pack(side="left", padx=(6, 0))
        self.module_reset_button = ttk.Button(
            module_actions, text="Reset", command=self.reset_current_module
        )
        self.module_reset_button.pack(side="right")
        self.manual_revert_button = ttk.Button(
            module_actions,
            text="撤销预览",
            command=self.revert_manual_parameters,
            state="disabled",
        )
        self.manual_revert_button.pack(side="right", padx=(0, 4))
        self.manual_apply_button = ttk.Button(
            module_actions,
            text="应用",
            command=self.apply_manual_parameters,
            state="disabled",
            style="Primary.TButton",
        )
        self.manual_apply_button.pack(side="right", padx=(0, 4))
        self.manual_revert_button.pack_forget()

        auto_card = ttk.Frame(right)
        self.auto_card = auto_card
        auto_card.pack(fill="x", pady=(0, 8))
        auto_header = ttk.Frame(auto_card)
        auto_header.pack(fill="x")
        self.auto_badge = StatusBadge(auto_header)
        self.auto_badge.pack(side="left")
        self.auto_confidence_var = tk.StringVar(value="No recommendation")
        ttk.Label(
            auto_header,
            textvariable=self.auto_confidence_var,
            style="Muted.TLabel",
        ).pack(side="left", padx=7)
        self.auto_message = InlineMessage(auto_card)
        self.auto_message.pack(fill="x", pady=(4, 0))
        self.auto_message.hide()
        auto_actions = ttk.Frame(auto_card)
        auto_actions.pack(fill="x", pady=(4, 0))
        self.auto_actions = auto_actions
        self.auto_analyze_button = ttk.Button(
            auto_actions,
            text="Auto",
            style="Primary.TButton",
            command=self.analyze_current_module,
        )
        self.auto_open_button = ttk.Button(
            auto_actions, text="Open", command=self.open_current_calibration
        )
        self.auto_preview_button = ttk.Button(
            auto_actions, text="Preview", command=self.preview_auto_suggestion
        )
        self.auto_apply_button = ttk.Button(
            auto_actions, text="Apply", command=self.apply_auto_suggestion
        )
        self.auto_revert_button = ttk.Button(
            auto_actions, text="Revert", command=self.revert_auto_suggestion
        )
        self.auto_cancel_button = ttk.Button(
            auto_actions, text="Cancel", command=self.revert_or_cancel_auto
        )
        self.auto_more_menu = ActionMenu(auto_actions, "More")
        self.auto_more_menu.add_command(
            "Open Calibration Workspace", self.open_current_calibration,
            enabled=lambda: self._auto_module_for_current() is not None,
        )
        self.auto_more_menu.add_command(
            "Analyze Again", self.reanalyze_current_module,
            enabled=lambda: self._auto_module_for_current() is not None,
        )
        self.auto_more_menu.add_command(
            "Export Recommendation…",
            self.export_current_recommendation,
            enabled=lambda: self._current_recommendation() is not None,
        )
        self.auto_analyze_button.pack(side="left")
        self.auto_more_menu.pack(side="right")
        self.parameters_separator = ttk.Separator(right)
        self.parameters_separator.pack(fill="x", pady=(0, 7))
        ttk.Label(right, text="PARAMETERS", style="Muted.TLabel").pack(
            anchor="w", pady=(0, 3)
        )
        manual_card = ttk.Frame(right)
        manual_card.pack(fill="both", expand=True)
        param_host = ttk.Frame(manual_card)
        param_host.pack(fill="both", expand=True)
        self.param_canvas = tk.Canvas(param_host, bg=PANEL, highlightthickness=0, width=310)
        scrollbar = ttk.Scrollbar(param_host, orient="vertical", command=self.param_canvas.yview)
        self.param_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.param_canvas.pack(side="left", fill="both", expand=True)
        self.param_frame = ttk.Frame(self.param_canvas)
        self.param_window = self.param_canvas.create_window((0, 0), window=self.param_frame, anchor="nw")
        self.param_frame.bind(
            "<Configure>",
            lambda _event: self.param_canvas.configure(scrollregion=self.param_canvas.bbox("all")),
        )
        self.param_canvas.bind(
            "<Configure>",
            lambda event: self.param_canvas.itemconfigure(self.param_window, width=event.width),
        )
        self.module_diagnostics_var = tk.StringVar(value="Waiting for preview")
        self.expert_diagnostics_label = ttk.Label(
            right, textvariable=self.module_diagnostics_var,
            style="Muted.TLabel", wraplength=300,
        )

        bottom = ttk.Frame(self.root, padding=(8, 4))
        self.analysis_container = bottom
        bottom.pack(fill="x")
        analysis_host = ttk.Frame(bottom)
        analysis_host.pack(side="left", fill="both", expand=True)
        self.analysis_host = analysis_host
        analysis_controls = ttk.Frame(analysis_host)
        analysis_controls.pack(fill="x")
        self.analysis_controls = analysis_controls
        self.analysis_toggle_button = ttk.Button(
            analysis_controls, text="Close",
            style="Secondary.TButton", command=self._toggle_analysis_panel,
        )
        self.analysis_toggle_button.pack(side="right")
        ttk.Label(
            analysis_controls, text="SCOPES", style="Title.TLabel"
        ).pack(side="left", padx=(0, 10))
        self.analysis_roi_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            analysis_controls,
            text="Analyze ROI",
            variable=self.analysis_roi_var,
            command=lambda: self.schedule_analysis_refresh(0),
        ).pack(side="left")
        self.waveform_mode_var = tk.StringVar(value="RGB Overlay")
        self.vectorscope_mode_var = tk.StringVar(value="YCbCr")
        self.vectorscope_scale_var = tk.DoubleVar(value=1.0)
        self.analysis_notebook = ttk.Notebook(analysis_host, height=150)
        self.analysis_notebook.pack(fill="both", expand=True)
        hist_tab = ttk.Frame(self.analysis_notebook)
        waveform_tab = ttk.Frame(self.analysis_notebook)
        vectorscope_tab = ttk.Frame(self.analysis_notebook)
        statistics_tab = ttk.Frame(self.analysis_notebook)
        self.analysis_notebook.add(hist_tab, text="Histogram")
        self.analysis_notebook.add(waveform_tab, text="Waveform")
        self.analysis_notebook.add(vectorscope_tab, text="Vectorscope")
        self.analysis_notebook.add(statistics_tab, text="Statistics")

        waveform_controls = ttk.Frame(waveform_tab)
        waveform_controls.pack(fill="x", padx=5, pady=3)
        ttk.Label(waveform_controls, text="Mode").pack(side="left")
        waveform_combo = ttk.Combobox(
            waveform_controls,
            textvariable=self.waveform_mode_var,
            values=("Luma", "RGB Overlay", "RGB Parade"),
            state="readonly",
            width=13,
        )
        waveform_combo.pack(side="left", padx=5)
        waveform_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.schedule_analysis_refresh(0),
        )

        vectorscope_controls = ttk.Frame(vectorscope_tab)
        vectorscope_controls.pack(fill="x", padx=5, pady=3)
        ttk.Label(vectorscope_controls, text="Mode").pack(side="left")
        vectorscope_combo = ttk.Combobox(
            vectorscope_controls,
            textvariable=self.vectorscope_mode_var,
            values=("YCbCr", "CIE 1976 u'v'"),
            state="readonly",
            width=14,
        )
        vectorscope_combo.pack(side="left", padx=5)
        vectorscope_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.schedule_analysis_refresh(0),
        )
        ttk.Label(vectorscope_controls, text="Scale").pack(
            side="left", padx=(8, 2)
        )
        vectorscope_scale = ttk.Combobox(
            vectorscope_controls,
            textvariable=self.vectorscope_scale_var,
            values=(0.5, 1.0, 1.5, 2.0),
            state="readonly",
            width=5,
        )
        vectorscope_scale.pack(side="left")
        vectorscope_scale.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.schedule_analysis_refresh(0),
        )
        self.hist_canvas = tk.Canvas(
            hist_tab, bg=COLORS["canvas_alt"], height=105,
            highlightthickness=0,
        )
        self.hist_canvas.pack(fill="both", expand=True)
        self.waveform_canvas = tk.Canvas(
            waveform_tab, bg=COLORS["canvas_alt"], height=105,
            highlightthickness=0,
        )
        self.waveform_canvas.pack(fill="both", expand=True)
        self.waveform_canvas.bind(
            "<Configure>",
            lambda _event: self._analysis_canvas_resized("Waveform"),
        )
        self.vectorscope_canvas = tk.Canvas(
            vectorscope_tab, bg=COLORS["canvas_alt"], height=105,
            highlightthickness=0,
        )
        self.vectorscope_canvas.pack(fill="both", expand=True)
        self.vectorscope_canvas.bind(
            "<Configure>",
            lambda _event: self._analysis_canvas_resized("Vectorscope"),
        )
        self.analysis_notebook.bind(
            "<<NotebookTabChanged>>",
            lambda _event: self.schedule_analysis_refresh(0),
        )
        self.metrics_label = ttk.Label(
            statistics_tab, text="", style="Muted.TLabel",
            justify="left", anchor="nw",
        )
        self.metrics_label.pack(fill="both", expand=True, padx=10, pady=8)
        if self.analysis_collapsed:
            bottom.pack_forget()
        self.status_var = tk.StringVar(value="就绪")
        self.performance_status_var = tk.StringVar(
            value="Pipeline -- · View -- · Analysis deferred · Cache --"
        )
        status_bar = tk.Frame(self.root, bg=COLORS["canvas_alt"])
        self.status_bar = status_bar
        status_bar.pack(fill="x")
        status = tk.Label(
            status_bar, textvariable=self.status_var,
            bg=COLORS["canvas_alt"], fg=MUTED,
            anchor="w", padx=8, pady=4,
        )
        status.pack(side="left", fill="x", expand=True)
        performance_status = tk.Label(
            status_bar, textvariable=self.performance_status_var,
            bg=COLORS["canvas_alt"], fg=MUTED,
            anchor="e", padx=8, pady=4,
        )
        self.performance_status_label = performance_status
        if self.expert_mode:
            performance_status.pack(side="right")

    @staticmethod
    def _is_text_input(widget) -> bool:
        return isinstance(
            widget,
            (
                tk.Entry,
                tk.Text,
                tk.Spinbox,
                ttk.Entry,
                ttk.Combobox,
                ttk.Spinbox,
            ),
        )

    def _shortcut(self, event, command, guard_text: bool = True):
        if (
            guard_text
            and event is not None
            and self._is_text_input(event.widget)
        ):
            return None
        command()
        return "break"

    def toggle_roi_mode(self) -> None:
        self.roi_mode_var.set(not self.roi_mode_var.get())
        self._roi_mode_changed()

    def revert_or_cancel_auto(self) -> None:
        if (
            self.calibration_workspace is None
            or not self.calibration_workspace.winfo_exists()
        ):
            return
        panel = self.calibration_workspace.auto_panel
        machine = panel.states[panel.module_var.get()]
        if machine.state.value == "RUNNING":
            panel.cancel_analysis()
        else:
            panel.revert()
        self._refresh_auto_summary()

    def _toggle_analysis_panel(self) -> None:
        requested = bool(self.analysis_panel_collapsed_var.get())
        if requested == self.analysis_collapsed:
            self.analysis_collapsed = not self.analysis_collapsed
        else:
            self.analysis_collapsed = requested
        self.analysis_panel_collapsed_var.set(self.analysis_collapsed)
        if self.analysis_collapsed:
            self._cancel_analysis_refresh()
            self.analysis_container.pack_forget()
            self.performance.set_value("analysis_state", "collapsed")
        else:
            self.analysis_container.pack(
                fill="x", before=self.status_bar
            )
            self.analysis_toggle_button.configure(text="Close")
            self.schedule_analysis_refresh(0)
        self._update_performance_status()

    def _cancel_analysis_refresh(self) -> None:
        self.analysis_generation += 1
        if self.analysis_pending_after is not None:
            try:
                self.root.after_cancel(self.analysis_pending_after)
            except tk.TclError:
                pass
            self.analysis_pending_after = None
            self.performance.increment("dropped_analysis_requests")
        if self.analysis_future is not None and not self.analysis_future.done():
            if self.analysis_future.cancel():
                self.performance.increment("dropped_analysis_requests")

    def _restore_main_sashes(self, values) -> None:
        for index, value in enumerate(values):
            if index >= len(self.main_paned.panes()) - 1:
                break
            try:
                self.main_paned.sashpos(index, int(value))
            except (TypeError, ValueError, tk.TclError):
                continue

    def _apply_expert_mode(self) -> None:
        self.expert_mode = bool(self.expert_mode_var.get())
        if self.expert_mode:
            if not self.stage_selector.winfo_manager():
                self.stage_selector.pack(side="left")
            if not self.expert_diagnostics_label.winfo_manager():
                self.expert_diagnostics_label.pack(
                    fill="x", pady=(7, 0)
                )
            if not self.performance_status_label.winfo_manager():
                self.performance_status_label.pack(side="right")
        else:
            self.stage_selector.pack_forget()
            self.expert_diagnostics_label.pack_forget()
            self.performance_status_label.pack_forget()
        if self.pipeline.modules:
            module = self.pipeline.modules[self.selected_module_index]
            self._build_parameter_editor(module)
        self._refresh_pipeline_list()

    def _refresh_pipeline_list(self) -> None:
        selected = self.selected_module_index
        self.pipeline_list.delete(0, "end")
        category_by_id = {
            "black_level_correction": "Sensor",
            "defective_pixel_correction": "Sensor",
            "lens_shading_correction": "Sensor",
            "white_balance": "Color",
            "demosaic": "Color",
            "color_correction_matrix": "Color",
            "tone_mapping": "Color",
            "noise_reduction": "Detail",
            "sharpen": "Detail",
            "color_adjustment": "Output",
        }
        auto_ids = {
            recommendation.target
            for recommendation in self.calibration_session.auto_recommendations.values()
        }
        for index, module in enumerate(self.pipeline.modules, 1):
            enabled = "●" if module.enabled else "○"
            suggested = "◆" if module.module_id in auto_ids else ""
            elapsed = ""
            if index - 1 < len(self.results):
                elapsed = f"{self.results[index - 1].elapsed_ms:.1f} ms"
            category = category_by_id.get(module.module_id, "Other")
            if self.expert_mode:
                text = (
                    f" {index:02d} {enabled}{suggested:1} "
                    f"[{category:<6}] {module.name}"
                )
                if elapsed:
                    text += f"  {elapsed}"
            else:
                text = f"  {enabled}  {module.name}"
                if suggested:
                    text += "  ◆"
                if elapsed:
                    text += f"   {elapsed}"
            self.pipeline_list.insert("end", text)
        if self.pipeline.modules:
            self.pipeline_list.selection_set(min(selected, len(self.pipeline.modules) - 1))
        names = ["00 · Input"] + [
            f"{index:02d} · {module.name}" for index, module in enumerate(self.pipeline.modules, 1)
        ]
        previous = self.stage_combo.current()
        self.stage_combo["values"] = names
        if previous < 0:
            previous = len(names) - 1
        self.stage_combo.current(min(previous, len(names) - 1))

    def _on_module_select(self) -> None:
        selection = self.pipeline_list.curselection()
        if not selection:
            return
        self.selected_module_index = int(selection[0])
        module = self.pipeline.modules[self.selected_module_index]
        self.module_title.configure(text=module.name)
        self.enabled_var.set(module.enabled)
        self._refresh_module_state()
        self.stage_combo.current(self.selected_module_index + 1)
        self._build_parameter_editor(module)
        self._refresh_auto_summary()
        if self.results:
            self._update_artifact_choices()
            self.render_current()

    def _refresh_module_state(self) -> None:
        module = self.pipeline.modules[self.selected_module_index]
        elapsed = (
            self.results[self.selected_module_index].elapsed_ms
            if self.selected_module_index < len(self.results) else None
        )
        state_text = "Enabled" if module.enabled else "Bypassed"
        timing_text = f"{elapsed:.2f} ms" if elapsed is not None else "waiting"
        dirty_text = (
            " · 参数预览待应用"
            if module.module_id in self.manual_dirty_modules
            else ""
        )
        self.module_state_var.set(
            f"{state_text} · {timing_text}{dirty_text}"
        )
        self._update_manual_action_state()

    @staticmethod
    def _module_edit_snapshot(module) -> Dict[str, object]:
        return copy.deepcopy(module.config())

    def _reset_manual_parameter_snapshots(self) -> None:
        self.manual_parameter_snapshots = {
            module.module_id: self._module_edit_snapshot(module)
            for module in self.pipeline.modules
        }
        self.manual_dirty_modules.clear()
        if hasattr(self, "manual_apply_button"):
            self._update_manual_action_state()

    def _mark_manual_parameter_state(self, module) -> None:
        baseline = self.manual_parameter_snapshots.get(module.module_id)
        current = self._module_edit_snapshot(module)
        if baseline is None:
            self.manual_parameter_snapshots[module.module_id] = current
            self.manual_dirty_modules.discard(module.module_id)
        elif current != baseline:
            self.manual_dirty_modules.add(module.module_id)
        else:
            self.manual_dirty_modules.discard(module.module_id)
        self._update_manual_action_state()

    def _update_manual_action_state(self) -> None:
        if not hasattr(self, "manual_apply_button"):
            return
        module = self.pipeline.modules[self.selected_module_index]
        dirty = module.module_id in self.manual_dirty_modules
        if dirty:
            self.module_reset_button.pack_forget()
            if not self.manual_revert_button.winfo_manager():
                self.manual_revert_button.pack(
                    side="right", padx=(0, 4)
                )
            if not self.manual_apply_button.winfo_manager():
                self.manual_apply_button.pack(
                    side="right", padx=(0, 4),
                    before=self.manual_revert_button,
                )
            self.manual_apply_button.configure(state="normal")
            self.manual_revert_button.configure(state="normal")
        else:
            if not self.module_reset_button.winfo_manager():
                self.module_reset_button.pack(side="right")
            if not self.manual_apply_button.winfo_manager():
                self.manual_apply_button.pack(
                    side="right", padx=(0, 4)
                )
            self.manual_apply_button.configure(state="disabled")
            self.manual_revert_button.pack_forget()

    def apply_manual_parameters(self) -> None:
        module = self.pipeline.modules[self.selected_module_index]
        self.manual_parameter_snapshots[module.module_id] = (
            self._module_edit_snapshot(module)
        )
        self.manual_dirty_modules.discard(module.module_id)
        self._store_current_work_item()
        self._refresh_module_state()
        self.toast.show(
            f"{module.name} 参数已应用到当前图像", "success"
        )

    def commit_module_parameters(self, module_id: str) -> None:
        """Commit an external calibration Apply into manual edit state."""

        module = self.pipeline.module_by_id(module_id)
        self.manual_parameter_snapshots[module_id] = (
            self._module_edit_snapshot(module)
        )
        self.manual_dirty_modules.discard(module_id)
        self._store_current_work_item()
        if (
            self.pipeline.modules[self.selected_module_index].module_id
            == module_id
        ):
            self._build_parameter_editor(module)
            self._refresh_module_state()

    def revert_manual_parameters(self) -> None:
        module = self.pipeline.modules[self.selected_module_index]
        baseline = self.manual_parameter_snapshots.get(module.module_id)
        if baseline is None:
            return
        module.enabled = bool(baseline.get("enabled", True))
        module.parameters = copy.deepcopy(
            baseline.get("parameters", module.parameters)
        )
        module.load_state(copy.deepcopy(baseline.get("state", {})))
        self.enabled_var.set(module.enabled)
        self.manual_dirty_modules.discard(module.module_id)
        self._build_parameter_editor(module)
        self._refresh_module_state()
        self.schedule_process(immediate=True)
        self.toast.show("已撤销当前模块的参数预览", "info")

    def brush_current_module_to_all(self) -> None:
        module_id = self.pipeline.modules[
            self.selected_module_index
        ].module_id
        self.apply_calibration_brush((module_id,))

    def brush_current_module_to_selected(self) -> None:
        if len(self.work_items) <= 1:
            return
        module_id = self.pipeline.modules[
            self.selected_module_index
        ].module_id
        dialog = tk.Toplevel(self.root)
        dialog.title("选择校准刷目标图像")
        dialog.geometry("460x390")
        dialog.transient(self.root)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text=f"将 {self.pipeline.modules[self.selected_module_index].name} "
            "应用到：",
            style="Title.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        listbox = tk.Listbox(
            body,
            selectmode="extended",
            bg=PANEL_2,
            fg=FG,
            selectbackground=COLORS["selection"],
            relief="flat",
        )
        listbox.pack(fill="both", expand=True)
        target_indices = []
        for index, item in enumerate(self.work_items):
            if index == self.current_image_index:
                continue
            target_indices.append(index)
            listbox.insert(
                "end", f"{index + 1} · {item.label}"
            )
        listbox.selection_set(0, "end")
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(
            actions, text="取消", command=dialog.destroy
        ).pack(side="right")

        def apply_selected() -> None:
            selected = [
                target_indices[int(position)]
                for position in listbox.curselection()
            ]
            if selected:
                self.apply_calibration_brush(
                    (module_id,), selected
                )
            dialog.destroy()

        ttk.Button(
            actions,
            text="应用到所选图像",
            style="Primary.TButton",
            command=apply_selected,
        ).pack(side="right", padx=(0, 6))

    def apply_calibration_brush(
        self,
        module_ids,
        target_indices=None,
    ) -> None:
        """Paint current calibration module states onto other work images."""

        module_ids = tuple(dict.fromkeys(module_ids))
        for module_id in module_ids:
            module = self.pipeline.module_by_id(module_id)
            self.manual_parameter_snapshots[module_id] = (
                self._module_edit_snapshot(module)
            )
            self.manual_dirty_modules.discard(module_id)
        self._update_manual_action_state()
        self._store_current_work_item()
        source_item = self.work_items[self.current_image_index]
        targets = (
            list(target_indices)
            if target_indices is not None
            else [
                index
                for index in range(len(self.work_items))
                if index != self.current_image_index
            ]
        )
        warnings = []
        applied = 0
        for index in targets:
            if not (
                0 <= index < len(self.work_items)
                and index != self.current_image_index
            ):
                continue
            target = self.work_items[index]
            compatibility = compatible_for_transfer(
                source_item.loaded, target.loaded, module_ids
            )
            warnings.extend(
                f"{target.label}: {warning}"
                for warning in compatibility
            )
            target.pipeline_snapshot = transfer_module_settings(
                source_item.pipeline_snapshot,
                target.pipeline_snapshot,
                module_ids,
            )
            if not target.manual_parameter_snapshots:
                target.manual_parameter_snapshots = {
                    item.get("id"): copy.deepcopy(item)
                    for item in target.pipeline_snapshot
                    if item.get("id")
                }
            target_configs = {
                item.get("id"): copy.deepcopy(item)
                for item in target.pipeline_snapshot
                if item.get("id") in module_ids
            }
            target.manual_parameter_snapshots.update(
                target_configs
            )
            target.manual_dirty_modules = [
                module_id
                for module_id in target.manual_dirty_modules
                if module_id not in module_ids
            ]
            if (
                "lens_shading_correction" in module_ids
                and source_item.calibration_session.lsc_mesh is not None
            ):
                target.calibration_session.lsc_mesh = (
                    source_item.calibration_session.lsc_mesh.copy()
                )
            target.calibration_session.calibration_history.append({
                "type": "calibration_brush",
                "source_image": source_item.label,
                "target_image": target.label,
                "module_ids": list(module_ids),
                "applied_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
            })
            applied += 1
        if applied == 0:
            self.toast.show("没有可应用的目标图像", "warning")
            return
        module_names = [
            self.pipeline.module_by_id(module_id).name
            for module_id in module_ids
        ]
        self.toast.show(
            f"校准刷已将 {', '.join(module_names)} 应用到 "
            f"{applied} 张图像",
            "success" if not warnings else "warning",
        )
        self._refresh_module_state()
        if warnings:
            self.status_var.set(
                f"校准刷已应用；兼容性提示：{warnings[0]}"
                + (
                    f"（另有 {len(warnings) - 1} 条）"
                    if len(warnings) > 1 else ""
                )
            )

    def _auto_module_for_current(self) -> Optional[str]:
        module_id = self.pipeline.modules[self.selected_module_index].module_id
        return {
            "black_level_correction": "BLC",
            "defective_pixel_correction": "DPC",
            "lens_shading_correction": "LSC",
            "white_balance": "AWB",
            "color_correction_matrix": "CCM",
            "tone_mapping": "Tone",
            "noise_reduction": "Noise Profile",
            "sharpen": "Sharpen",
        }.get(module_id)

    def _current_recommendation(self):
        name = self._auto_module_for_current()
        if name is None:
            return None
        recommendations = self.calibration_session.auto_recommendations
        for identifier in AUTO_RECOMMENDATION_IDS[name]:
            if identifier in recommendations:
                return recommendations[identifier]
        return None

    def _refresh_auto_summary(self) -> None:
        name = self._auto_module_for_current()
        recommendation = self._current_recommendation()
        if name is None:
            self.auto_card.pack_forget()
        elif not self.auto_card.winfo_manager():
            self.auto_card.pack(
                fill="x",
                pady=(0, 8),
                before=self.parameters_separator,
            )
        machine = None
        if (
            name
            and self.calibration_workspace is not None
            and self.calibration_workspace.winfo_exists()
        ):
            machine = self.calibration_workspace.auto_panel.states[name]
        if machine is not None:
            state = machine.state
            can_analyze = machine.can_analyze
            can_preview = (
                recommendation is not None and machine.can_preview
            )
            can_apply = (
                recommendation is not None and machine.can_apply
            )
            can_revert = machine.can_revert
        else:
            state = (
                "APPLIED"
                if recommendation is not None and recommendation.applied
                else "SUGGESTED"
                if recommendation is not None
                else "NOT_ANALYZED"
            )
            can_analyze = name is not None
            can_preview = recommendation is not None and state == "SUGGESTED"
            can_apply = False
            can_revert = False
        self.auto_badge.set_state(state)
        if recommendation is None:
            self.auto_confidence_var.set(
                "This module has no analyzer"
                if name is None else "No recommendation"
            )
            self.auto_message.hide()
        else:
            self.auto_confidence_var.set(
                f"Confidence {recommendation.confidence * 100:.1f}% · "
                f"{recommendation.elapsed_ms:.1f} ms"
            )
            if recommendation.warnings:
                self.auto_message.show(
                    f"{len(recommendation.warnings)} warning(s): "
                    f"{recommendation.warnings[0]}",
                    "warning",
                )
            else:
                self.auto_message.hide()
        self.auto_analyze_button.configure(
            state="normal" if can_analyze else "disabled"
        )
        self.auto_open_button.configure(
            state="normal" if name is not None else "disabled"
        )
        self.auto_preview_button.configure(
            state="normal" if can_preview else "disabled"
        )
        self.auto_apply_button.configure(
            state="normal" if can_apply else "disabled"
        )
        self.auto_revert_button.configure(
            state="normal" if can_revert else "disabled"
        )
        state_value = getattr(state, "value", str(state))
        for widget in (
            self.auto_analyze_button,
            self.auto_open_button,
            self.auto_preview_button,
            self.auto_apply_button,
            self.auto_revert_button,
            self.auto_cancel_button,
            self.auto_more_menu,
        ):
            widget.pack_forget()
        if name is not None:
            if state_value == "RUNNING":
                self.auto_cancel_button.pack(side="left")
            elif state_value == "SUGGESTED":
                self.auto_preview_button.pack(side="left")
            elif state_value == "PREVIEWING":
                self.auto_apply_button.pack(side="left")
                self.auto_revert_button.pack(side="left", padx=3)
            elif state_value == "APPLIED":
                self.auto_analyze_button.configure(
                    text="Analyze Again",
                    command=self.reanalyze_current_module,
                    state="normal",
                )
                self.auto_analyze_button.pack(side="left")
            else:
                label = (
                    "Re-Analyze"
                    if state_value in {"STALE", "FAILED", "CANCELLED"}
                    else "Auto"
                )
                self.auto_analyze_button.configure(
                    text=label,
                    command=self.analyze_current_module,
                    state="normal" if can_analyze else "disabled",
                )
                self.auto_analyze_button.pack(side="left")
            self.auto_more_menu.pack(side="right")

    def open_current_calibration(self) -> None:
        name = self._auto_module_for_current()
        if name is None:
            return
        self.open_calibration_workspace()
        if self.calibration_workspace is not None:
            self.calibration_workspace.select_auto_module(name)
        self._refresh_auto_summary()

    def analyze_current_module(self) -> None:
        if self._auto_module_for_current() is None:
            return
        self.open_current_calibration()
        if self.calibration_workspace is not None:
            self.calibration_workspace.auto_panel.analyze()
        self._refresh_auto_summary()

    def reanalyze_current_module(self) -> None:
        name = self._auto_module_for_current()
        if name is None:
            return
        self.open_current_calibration()
        panel = self.calibration_workspace.auto_panel
        machine = panel.states[name]
        state_value = machine.state.value
        if state_value == "PREVIEWING":
            panel.revert()
            state_value = machine.state.value
        if state_value in {"SUGGESTED", "APPLIED"}:
            from .calibration_state import CalibrationUIState
            machine.transition(CalibrationUIState.STALE)
        panel.analyze()
        self._refresh_auto_summary()

    def export_current_recommendation(self) -> None:
        if self._current_recommendation() is None:
            return
        self.open_current_calibration()
        self.calibration_workspace.auto_panel.export_result()

    def preview_auto_suggestion(self) -> None:
        if self._auto_module_for_current() is None:
            return
        self.open_current_calibration()
        if self.calibration_workspace is not None:
            self.calibration_workspace.auto_panel.preview()
        self._refresh_auto_summary()

    def apply_auto_suggestion(self) -> None:
        if (
            self.calibration_workspace is not None
            and self.calibration_workspace.winfo_exists()
        ):
            self.calibration_workspace.auto_panel.apply()
            self._refresh_auto_summary()
            self._refresh_pipeline_list()

    def revert_auto_suggestion(self) -> None:
        if (
            self.calibration_workspace is not None
            and self.calibration_workspace.winfo_exists()
        ):
            self.calibration_workspace.auto_panel.revert()
            self._refresh_auto_summary()

    def _on_stage_changed(self, _event=None) -> None:
        self._update_artifact_choices()
        if (
            self.pending_artifact
            and self.pending_artifact in self.artifact_combo["values"]
        ):
            self.artifact_var.set(self.pending_artifact)
        self.pending_artifact = None
        self.render_current(schedule_analysis=True)
        self._refresh_pipeline_list()
        self._refresh_module_state()
        self._refresh_auto_summary()

    def _update_artifact_choices(self) -> None:
        choices = ["Main Output"]
        if self.results:
            result = self.results[self._current_result_index()]
            choices.extend(result.artifacts.keys())
        current = self.artifact_var.get()
        self.artifact_combo["values"] = choices
        if current not in choices:
            self.artifact_var.set("Main Output")
        if hasattr(self, "artifact_submenu"):
            self.artifact_submenu.delete(0, "end")
            for choice in choices:
                self.artifact_submenu.add_radiobutton(
                    label=choice,
                    variable=self.artifact_var,
                    value=choice,
                    command=lambda: self.render_current(
                        schedule_analysis=False
                    ),
                )

    def _build_parameter_editor(self, module) -> None:
        for child in self.param_frame.winfo_children():
            child.destroy()
        self.param_vars.clear()
        self.tone_curve_canvas = None
        self.ccm_info_label = None
        basic_params = ttk.Frame(self.param_frame)
        basic_params.pack(fill="x")
        advanced_params = ttk.Frame(self.param_frame)
        self.advanced_params_frame = advanced_params
        basic_keys = BASIC_PARAMETER_KEYS.get(
            module.module_id, set(module.specs)
        )
        matrix_keys = [key for key in module.specs if key.startswith("m") and len(key) == 3]
        handled_matrix = False
        for spec in module.specs.values():
            if spec.key in matrix_keys:
                if handled_matrix:
                    continue
                handled_matrix = True
                ttk.Label(basic_params, text="3 × 3 Matrix", style="Title.TLabel").pack(
                    anchor="w", pady=(8, 4)
                )
                matrix_frame = ttk.Frame(basic_params)
                matrix_frame.pack(fill="x", pady=(0, 8))
                for key in matrix_keys:
                    row, col = int(key[1]), int(key[2])
                    var = tk.StringVar(value=self._format_value(module.parameters[key]))
                    self.param_vars[key] = var
                    entry = ttk.Entry(matrix_frame, textvariable=var, width=8)
                    entry.grid(row=row, column=col, padx=2, pady=2, sticky="ew")
                    var.trace_add(
                        "write",
                        lambda *_args, k=key:
                        self._parameter_changed(k),
                    )
                    entry.bind("<Return>", lambda _event, k=key: self._entry_commit(k))
                    entry.bind("<FocusOut>", lambda _event, k=key: self._entry_commit(k))
                matrix_controls = ttk.Frame(basic_params)
                matrix_controls.pack(fill="x", pady=(0, 5))
                ttk.Button(
                    matrix_controls, text="Identity", command=self._ccm_identity
                ).pack(side="left")
                ccm_menu = ActionMenu(matrix_controls, "CCM")
                ccm_menu.add_command(
                    "Normalize rows", self._ccm_normalize_rows
                )
                ccm_menu.add_command("Copy matrix", self._ccm_copy)
                ccm_menu.add_command("Paste matrix", self._ccm_paste)
                ccm_menu.add_separator()
                ccm_menu.add_command("Import…", self._ccm_import)
                ccm_menu.add_command("Export…", self._ccm_export)
                ccm_menu.pack(side="left", padx=4)
                self.ccm_info_label = ttk.Label(
                    basic_params, text="", style="Muted.TLabel"
                )
                self.ccm_info_label.pack(anchor="w", pady=(0, 8))
                continue
            parent = (
                basic_params
                if spec.key in basic_keys else advanced_params
            )
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=spec.label).pack(anchor="w")
            if spec.kind == "bool":
                var = tk.BooleanVar(value=bool(module.parameters[spec.key]))
                self.param_vars[spec.key] = var
                ttk.Checkbutton(
                    row, text="Enabled", variable=var,
                    command=lambda k=spec.key: self._parameter_changed(k),
                ).pack(anchor="w", pady=(2, 0))
            elif spec.kind == "choice":
                var = tk.StringVar(value=str(module.parameters[spec.key]))
                self.param_vars[spec.key] = var
                combo = ttk.Combobox(
                    row, textvariable=var, values=spec.choices, state="readonly"
                )
                combo.pack(fill="x", pady=(2, 0))
                combo.bind(
                    "<<ComboboxSelected>>",
                    lambda _event, k=spec.key: self._parameter_changed(k),
                )
            else:
                inner = ttk.Frame(row)
                inner.pack(fill="x", pady=(2, 0))
                var = tk.DoubleVar(value=float(module.parameters[spec.key]))
                self.param_vars[spec.key] = var
                scale = ttk.Scale(
                    inner, from_=float(spec.minimum), to=float(spec.maximum), variable=var,
                    command=lambda _value, k=spec.key: self._parameter_changed(k),
                )
                scale.pack(side="left", fill="x", expand=True)
                text_var = tk.StringVar(value=self._format_value(module.parameters[spec.key]))
                entry = ttk.Entry(inner, textvariable=text_var, width=8)
                entry.pack(side="right", padx=(8, 0))

                def sync_entry(*_args, variable=var, text=text_var, parameter=spec):
                    value = variable.get()
                    if parameter.kind == "int":
                        value = int(round(value))
                    text.set(self._format_value(value))

                var.trace_add("write", sync_entry)

                def commit_entry(_event=None, variable=var, text=text_var, parameter=spec):
                    try:
                        value = float(text.get())
                        value = max(float(parameter.minimum), min(float(parameter.maximum), value))
                        variable.set(int(round(value)) if parameter.kind == "int" else value)
                    except (ValueError, tk.TclError):
                        text.set(self._format_value(variable.get()))
                    self._parameter_changed(parameter.key)

                entry.bind("<Return>", commit_entry)
                entry.bind("<FocusOut>", commit_entry)
        if module.module_id == "tone_mapping":
            ttk.Label(
                advanced_params, text="Transfer Curve", style="Title.TLabel"
            ).pack(anchor="w", pady=(10, 4))
            self.tone_curve_canvas = tk.Canvas(
                advanced_params,
                width=280,
                height=180,
                bg=COLORS["canvas_alt"],
                highlightthickness=1,
                highlightbackground=COLORS["border"],
            )
            self.tone_curve_canvas.pack(fill="x")
            self.tone_curve_canvas.bind(
                "<Configure>", lambda _event: self._draw_tone_curve()
            )
        if advanced_params.winfo_children():
            self.advanced_params_button = ttk.Button(
                self.param_frame,
                text="▸ Advanced",
                command=self._toggle_advanced_parameters,
            )
            self.advanced_params_button.pack(fill="x", pady=(8, 3))
            expanded = (
                self.expert_mode
                or self.advanced_param_state.get(module.module_id, False)
            )
            if expanded:
                advanced_params.pack(fill="x")
                self.advanced_params_button.configure(text="▾ Advanced")
        else:
            self.advanced_params_button = None
        self._draw_tone_curve()
        self._update_ccm_info()

    def _toggle_advanced_parameters(self) -> None:
        frame = self.advanced_params_frame
        button = self.advanced_params_button
        if frame is None or button is None:
            return
        module_id = self.pipeline.modules[
            self.selected_module_index
        ].module_id
        expanded = bool(frame.winfo_manager())
        if expanded:
            frame.pack_forget()
            button.configure(text="▸ Advanced")
        else:
            frame.pack(fill="x")
            button.configure(text="▾ Advanced")
        self.advanced_param_state[module_id] = not expanded

    @staticmethod
    def _format_value(value) -> str:
        if isinstance(value, (int, np.integer)):
            return str(int(value))
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.4g}"
        return str(value)

    def _entry_commit(self, key: str) -> None:
        self._parameter_changed(key)

    def _parameter_changed(self, key: str) -> None:
        module = self.pipeline.modules[self.selected_module_index]
        variable = self.param_vars.get(key)
        if variable is None:
            return
        try:
            value = variable.get()
            spec = module.specs[key]
            if spec.kind == "int":
                value = int(round(float(value)))
            elif spec.kind == "float":
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError("parameter must be finite")
            module.parameters[key] = value
        except (ValueError, tk.TclError):
            return
        self._draw_tone_curve()
        self._update_ccm_info()
        name = self._auto_module_for_current()
        if (
            name is not None
            and self.calibration_workspace is not None
            and self.calibration_workspace.winfo_exists()
        ):
            panel = self.calibration_workspace.auto_panel
            machine = panel.states[name]
            changed = False
            if machine.state.value == "PREVIEWING":
                edited = copy.deepcopy(module.parameters)
                panel.controller.revert()
                module.parameters.update(edited)
                machine.transition("SUGGESTED")
                machine.transition("STALE")
                panel.preview_banner.hide()
                changed = True
            else:
                changed = machine.mark_stale_if_changed(module.parameters)
            if changed:
                panel.message.show(
                    "手工参数已变化，旧 Recommendation 已标记为 Stale。",
                    "warning",
                )
                panel._refresh_navigation()
                panel._update_action_states()
        self._mark_manual_parameter_state(module)
        self._refresh_auto_summary()
        self._refresh_module_state()
        self.schedule_process()

    def _draw_tone_curve(self) -> None:
        canvas = self.tone_curve_canvas
        if canvas is None or not canvas.winfo_exists():
            return
        module = self.pipeline.modules[self.selected_module_index]
        if module.module_id != "tone_mapping":
            return
        width = max(canvas.winfo_width(), 280)
        height = max(canvas.winfo_height(), 180)
        pad = 18
        canvas.delete("all")
        for fraction in (0.25, 0.5, 0.75):
            x = pad + fraction * (width - 2 * pad)
            y = pad + fraction * (height - 2 * pad)
            canvas.create_line(
                x, pad, x, height - pad, fill=COLORS["grid"]
            )
            canvas.create_line(
                pad, y, width - pad, y, fill=COLORS["grid"]
            )
        canvas.create_line(
            pad, height - pad, width - pad, pad,
            fill=COLORS["guide"], dash=(3, 3),
        )
        x_values = np.linspace(0, 1, 257, dtype=np.float32)
        y_values = evaluate_tone_curve(x_values, module.parameters)
        points = []
        for x_value, y_value in zip(x_values, y_values):
            points.extend((
                pad + float(x_value) * (width - 2 * pad),
                height - pad - float(y_value) * (height - 2 * pad),
            ))
        canvas.create_line(*points, fill=ACCENT, width=2)
        for key, color in (("black_point", RED), ("white_point", GREEN)):
            x_value = float(module.parameters[key])
            x = pad + np.clip(x_value, 0, 1) * (width - 2 * pad)
            canvas.create_line(x, pad, x, height - pad, fill=color, dash=(4, 2))
        canvas.create_text(
            pad, 4, text="OUTPUT", anchor="nw", fill=MUTED, font=FONTS["small"]
        )
        canvas.create_text(
            width - pad, height - 4, text="INPUT", anchor="se",
            fill=MUTED, font=FONTS["small"],
        )

    def _ccm_module(self):
        return self.pipeline.module_by_id("color_correction_matrix")

    def _set_ccm_values(self, values: np.ndarray) -> None:
        matrix = np.asarray(values, dtype=np.float32).reshape(3, 3)
        module = self._ccm_module()
        for row in range(3):
            for col in range(3):
                key = f"m{row}{col}"
                module.parameters[key] = float(matrix[row, col])
                variable = self.param_vars.get(key)
                if variable is not None:
                    variable.set(self._format_value(matrix[row, col]))
        self._mark_manual_parameter_state(module)
        self._update_ccm_info()
        self._refresh_module_state()
        self.schedule_process(immediate=True)

    def _ccm_identity(self) -> None:
        self._set_ccm_values(np.eye(3, dtype=np.float32))

    def _ccm_normalize_rows(self) -> None:
        matrix = self._ccm_module().matrix()
        sums = matrix.sum(axis=1, keepdims=True)
        if np.any(np.abs(sums) < 1e-8):
            messagebox.showwarning(
                "CCM", "至少一行的和接近 0，无法进行行归一化。", parent=self.root
            )
            return
        self._set_ccm_values(matrix / sums)

    def _ccm_copy(self) -> None:
        matrix = self._ccm_module().matrix()
        text = "\n".join("\t".join(f"{value:.8g}" for value in row) for row in matrix)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("CCM 已复制到剪贴板")

    def _parse_ccm_text(self, text: str) -> np.ndarray:
        values = [
            float(token)
            for token in re.split(r"[\s,;，]+", text.strip())
            if token
        ]
        if len(values) != 9 or not np.all(np.isfinite(values)):
            raise ValueError("CCM 必须包含 9 个有限数值")
        return np.asarray(values, dtype=np.float32).reshape(3, 3)

    def _ccm_paste(self) -> None:
        try:
            self._set_ccm_values(self._parse_ccm_text(self.root.clipboard_get()))
        except Exception as exc:
            messagebox.showerror("粘贴 CCM 失败", str(exc), parent=self.root)

    def _ccm_export(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出 CCM",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        module = self._ccm_module()
        payload = {
            "matrix": module.matrix().tolist(),
            "offset": [
                module.parameters["offset_r"],
                module.parameters["offset_g"],
                module.parameters["offset_b"],
            ],
            "strength": module.parameters["strength"],
        }
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.status_var.set(f"CCM 已导出：{path}")

    def _ccm_import(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="导入 CCM", filetypes=[("JSON", "*.json")]
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self._set_ccm_values(np.asarray(payload["matrix"], dtype=np.float32))
            module = self._ccm_module()
            for key, value in zip(
                ("offset_r", "offset_g", "offset_b"), payload.get("offset", [0, 0, 0])
            ):
                module.parameters[key] = float(value)
            module.parameters["strength"] = float(payload.get("strength", 1.0))
            self._build_parameter_editor(module)
            self._mark_manual_parameter_state(module)
            self._refresh_module_state()
            self.schedule_process(immediate=True)
        except Exception as exc:
            messagebox.showerror("导入 CCM 失败", str(exc), parent=self.root)

    def _update_ccm_info(self) -> None:
        if self.ccm_info_label is None or not self.ccm_info_label.winfo_exists():
            return
        determinant = float(np.linalg.det(self._ccm_module().matrix()))
        warning = abs(determinant) < 1e-4
        self.ccm_info_label.configure(
            text=f"Determinant: {determinant:.6g}"
            + ("  ·  Warning: near singular" if warning else ""),
            foreground=RED if warning else MUTED,
        )

    def _toggle_module(self) -> None:
        module = self.pipeline.modules[self.selected_module_index]
        module.enabled = bool(self.enabled_var.get())
        self._mark_manual_parameter_state(module)
        self.module_state_var.set(
            "Enabled · processing" if module.enabled else "Bypassed"
        )
        self._refresh_pipeline_list()
        self.schedule_process(immediate=True)

    def reset_current_module(self) -> None:
        module = self.pipeline.modules[self.selected_module_index]
        module.reset()
        if module.module_id == "black_level_correction":
            module.sync_metadata(self.loaded.metadata)
        self._mark_manual_parameter_state(module)
        self._build_parameter_editor(module)
        self._refresh_module_state()
        self.schedule_process(immediate=True)

    def _sync_blc_to_metadata(self) -> None:
        self.pipeline.module_by_id("black_level_correction").sync_metadata(self.loaded.metadata)

    def _prepare_preview(self) -> None:
        if self.loaded.domain == "bayer":
            self.preview_image = resize_bayer_preview(
                self.loaded.image, self.loaded.metadata.bayer_pattern, max_side=1500
            )
        else:
            image = self.loaded.image
            h, w = image.shape[:2]
            if max(h, w) > 1500:
                import cv2
                scale = 1500 / max(h, w)
                image = cv2.resize(
                    image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
                )
            self.preview_image = np.asarray(image, dtype=np.float32)

    def schedule_process(self, immediate: bool = False) -> None:
        if self.pending_after:
            self.root.after_cancel(self.pending_after)
            self.pending_after = None
        delay = 1 if immediate else 90
        self.pending_after = self.root.after(delay, self._start_process)

    def _start_process(self) -> None:
        self.pending_after = None
        self.generation += 1
        generation = self.generation
        snapshot = copy.deepcopy(self.pipeline.snapshot())
        image = np.asarray(self.preview_image, dtype=np.float32).copy()
        metadata = copy.deepcopy(self.loaded.metadata)
        domain = self.loaded.domain
        input_revision = self.input_revision
        roi = self.roi if self.roi_process_var.get() else None
        self.status_var.set("处理中…")
        if self.current_future is not None and not self.current_future.done():
            # Cancels a queued stale preview. A running NumPy/OpenCV call cannot
            # be interrupted safely, but generation checks discard its result.
            self.current_future.cancel()
        future = self.executor.submit(
            self.pipeline.process_cached,
            image,
            domain,
            metadata,
            snapshot,
            self.pipeline_cache,
            input_revision,
            roi,
            24,
        )
        self.current_future = future
        self._schedule_future_poll(future, generation)

    def _schedule_future_poll(
        self, future: Future, generation: int
    ) -> None:
        after_id: Optional[str] = None

        def poll() -> None:
            if after_id is not None:
                self.poll_after_ids.discard(after_id)
            self._poll_future(future, generation)

        after_id = self.root.after(15, poll)
        self.poll_after_ids.add(after_id)

    def _poll_future(self, future: Future, generation: int) -> None:
        if not future.done():
            self._schedule_future_poll(future, generation)
            return
        if generation != self.generation:
            self.performance.increment("dropped_pipeline_results")
            return
        try:
            self.results = future.result()
        except Exception as exc:
            self.status_var.set(f"处理失败：{exc}")
            messagebox.showerror(
                "ISP 处理失败", f"{exc}\n\n{traceback.format_exc(limit=4)}", parent=self.root
            )
            return
        run_metrics = self.pipeline_cache.get("last_metrics", {})
        cache_hits = run_metrics.get("cache_hits", 0)
        recomputed = run_metrics.get("recomputed", len(self.pipeline.modules))
        total = run_metrics.get(
            "elapsed_ms", sum(result.elapsed_ms for result in self.results)
        )
        self.result_revision += 1
        self.render_cache.clear()
        self._raster_key = None
        self.performance.record("pipeline", total)
        self.performance.set_value(
            "pipeline_cache", f"{cache_hits}/{cache_hits + recomputed}"
        )
        memory_bytes = 0
        for result in self.results:
            memory_bytes += int(getattr(result.image, "nbytes", 0))
            memory_bytes += sum(
                int(getattr(value, "nbytes", 0))
                for value in result.artifacts.values()
            )
        self.performance.set_value(
            "preview_size",
            f"{self.preview_image.shape[1]}×{self.preview_image.shape[0]}",
        )
        self.performance.set_value(
            "result_memory_estimate",
            f"{memory_bytes / (1024 * 1024):.1f} MiB",
        )
        roi_text = (
            f" · ROI {self.roi.width}×{self.roi.height}"
            if self.roi_process_var.get() and self.roi else ""
        )
        if self.expert_mode:
            self.status_var.set(
                f"预览完成 · {self.preview_image.shape[1]}×{self.preview_image.shape[0]} · "
                f"{total:.1f} ms · cache {cache_hits} / recompute {recomputed}"
                f"{roi_text} · {self.loaded.description}"
            )
        else:
            self.status_var.set(
                f"Ready · {self.preview_image.shape[1]}×"
                f"{self.preview_image.shape[0]} · {total:.1f} ms"
                f"{roi_text}"
            )
        self._update_artifact_choices()
        if (
            self.pending_artifact
            and self.pending_artifact in self.artifact_combo["values"]
        ):
            self.artifact_var.set(self.pending_artifact)
        self.pending_artifact = None
        self.render_current(schedule_analysis=True)
        self._refresh_pipeline_list()
        self._refresh_module_state()
        self._refresh_auto_summary()

    def _current_result_index(self) -> int:
        index = self.stage_combo.current()
        if not self.results:
            return 0
        return max(0, min(index, len(self.results) - 1))

    def _apply_view_options(self, rgb: np.ndarray) -> np.ndarray:
        rgb = np.asarray(rgb, dtype=np.float32).copy()
        channel = self.channel_var.get()
        if channel in {"R", "G", "B"}:
            idx = {"R": 0, "G": 1, "B": 2}[channel]
            single = rgb[:, :, idx]
            rgb = np.repeat(single[:, :, None], 3, axis=2)
        elif channel == "Luma":
            single = np.sum(rgb * np.array([0.2126, 0.7152, 0.0722], np.float32), axis=2)
            rgb = np.repeat(single[:, :, None], 3, axis=2)
        if self.clipping_var.get():
            luminance = np.mean(rgb, axis=2)
            rgb[luminance >= 0.995] = (1.0, 0.0, 0.6)
            rgb[luminance <= 0.002] = (0.0, 0.45, 1.0)
        return np.clip(rgb, 0, 1)

    def _stage_rgb(self, index: int) -> np.ndarray:
        result = self.results[index]
        key = self.render_cache.stage_key(
            self.result_revision,
            index,
            result.domain,
            self.input_revision,
        )
        main = self.render_cache.get_stage(key)
        if main is None:
            started = time.perf_counter()
            main = display_rgb(
                result.image, result.domain, self.loaded.metadata
            )
            main = np.asarray(main, dtype=np.float32)
            main.setflags(write=False)
            self.render_cache.put_stage(key, main)
            self.performance.record(
                "stage_rgb", (time.perf_counter() - started) * 1000.0
            )
        return main

    def _result_rgb(self, index: int, include_artifact: bool = True) -> np.ndarray:
        result = self.results[index]
        main = self._stage_rgb(index)
        artifact_name = self.artifact_var.get() if include_artifact else "Main Output"
        if artifact_name != "Main Output" and artifact_name in result.artifacts:
            artifact = artifact_to_rgb(artifact_name, result.artifacts[artifact_name])
            if self.artifact_overlay_var.get():
                if artifact_name == "Defect Mask":
                    mask = np.any(artifact > 0, axis=2, keepdims=True)
                    main = np.where(mask, main * 0.25 + artifact * 0.75, main)
                else:
                    main = main * 0.35 + artifact * 0.65
            else:
                main = artifact
        return self._apply_view_options(main)

    def _current_rgb(self) -> np.ndarray:
        return self._result_rgb(self._current_result_index(), include_artifact=True)

    def render_current(self, schedule_analysis: bool = False) -> None:
        if not self.results:
            return
        started = time.perf_counter()
        index = self._current_result_index()
        rgb = self._current_rgb()
        if index > 0 and (self.compare_var.get() or self.temporary_input):
            before = self._result_rgb(index - 1, include_artifact=False)
            if before.shape[:2] != rgb.shape[:2]:
                import cv2
                before = cv2.resize(before, (rgb.shape[1], rgb.shape[0]))
            if self.temporary_input:
                rgb = before
            else:
                split = int(np.clip(self.compare_position, 0, 1) * rgb.shape[1])
                composite = rgb.copy()
                composite[:, :split] = before[:, :split]
                rgb = composite
        self.display_array = np.clip(rgb, 0, 1)
        self._display_revision += 1
        self._raster_key = None
        self._render_canvas_image()
        self.performance.record(
            "view", (time.perf_counter() - started) * 1000.0
        )
        if schedule_analysis:
            self.schedule_analysis_refresh()
        self._update_performance_status()

    def _render_canvas_image(self) -> None:
        if self.display_array is None:
            return
        canvas_w = max(self.image_canvas.winfo_width(), 10)
        canvas_h = max(self.image_canvas.winfo_height(), 10)
        image_h, image_w = self.display_array.shape[:2]
        if self.fit_mode:
            self.zoom = min(canvas_w / image_w, canvas_h / image_h, 1.0)
            self.canvas_origin = [
                (canvas_w - image_w * self.zoom) / 2,
                (canvas_h - image_h * self.zoom) / 2,
            ]
        target_w = max(1, int(image_w * self.zoom))
        target_h = max(1, int(image_h * self.zoom))
        resampling = (
            Image.Resampling.LANCZOS
            if self.zoom < 1 else Image.Resampling.NEAREST
        )
        raster_key = (
            self._display_revision,
            target_w,
            target_h,
            int(resampling),
        )
        if raster_key != self._raster_key or self._raster_photo is None:
            raster_started = time.perf_counter()
            array8 = np.round(self.display_array * 255.0).astype(np.uint8)
            pil = Image.fromarray(array8)
            pil = pil.resize((target_w, target_h), resampling)
            self._raster_photo = ImageTk.PhotoImage(pil)
            self._raster_key = raster_key
            self.performance.record(
                "raster", (time.perf_counter() - raster_started) * 1000.0
            )
        self.photo = self._raster_photo
        self.image_canvas.delete("all")
        self.image_canvas.create_image(
            self.canvas_origin[0], self.canvas_origin[1], image=self.photo, anchor="nw"
        )
        if (
            self.compare_var.get()
            and self._current_result_index() > 0
            and not self.temporary_input
        ):
            divider_x = self.canvas_origin[0] + image_w * self.compare_position * self.zoom
            self.image_canvas.create_line(
                divider_x, self.canvas_origin[1], divider_x,
                self.canvas_origin[1] + target_h, fill="white", width=2,
            )
            handle_y = self.canvas_origin[1] + target_h / 2
            self.image_canvas.create_oval(
                divider_x - 8, handle_y - 8, divider_x + 8, handle_y + 8,
                fill="white", outline=COLORS["panel_alt"], width=2,
            )
            self.image_canvas.create_text(
                self.canvas_origin[0] + 12, self.canvas_origin[1] + 12,
                text="INPUT", anchor="nw", fill="white",
                font=FONTS["section"],
            )
            self.image_canvas.create_text(
                divider_x + 12, self.canvas_origin[1] + 12,
                text="OUTPUT", anchor="nw", fill="white",
                font=FONTS["section"],
            )
        result = self.results[self._current_result_index()]
        roi_text = (
            f"{self.roi.width}×{self.roi.height}"
            if self.roi is not None else "Full"
        )
        overlay_text = (
            f"{result.name} · {result.domain.upper()} · "
            f"{self.zoom * 100:.0f}% · ROI {roi_text}"
        )
        self.image_canvas.create_text(
            canvas_w - 10, 10, text=overlay_text, anchor="ne",
            fill=FG, font=FONTS["body"], tags="view_info",
        )
        if self.roi is not None and not self.rois:
            self.rois = [self.roi]
            self.active_roi_index = 0
        if self.rois and not self.roi_process_var.get():
            for index, roi in enumerate(self.rois):
                x0 = self.canvas_origin[0] + roi.x * self.zoom
                y0 = self.canvas_origin[1] + roi.y * self.zoom
                x1 = self.canvas_origin[0] + roi.x2 * self.zoom
                y1 = self.canvas_origin[1] + roi.y2 * self.zoom
                active = index == self.active_roi_index
                color = (
                    COLORS["candidate"]
                    if active else COLORS["guide"]
                )
                self.image_canvas.create_rectangle(
                    x0, y0, x1, y1,
                    outline=color,
                    width=2 if active else 1,
                    dash=() if active else (5, 3),
                    tags="roi",
                )
                self.image_canvas.create_text(
                    x0 + 4, y0 + 4,
                    text=str(index + 1),
                    anchor="nw",
                    fill=color,
                    font=FONTS["small"],
                    tags="roi",
                )
                if active and self.roi_mode_var.get():
                    handle_size = 4
                    for hx, hy in (
                        (x0, y0),
                        ((x0 + x1) / 2, y0),
                        (x1, y0),
                        (x1, (y0 + y1) / 2),
                        (x1, y1),
                        ((x0 + x1) / 2, y1),
                        (x0, y1),
                        (x0, (y0 + y1) / 2),
                    ):
                        self.image_canvas.create_rectangle(
                            hx - handle_size,
                            hy - handle_size,
                            hx + handle_size,
                            hy + handle_size,
                            fill=color,
                            outline=COLORS["panel_alt"],
                            tags="roi",
                        )
        if self.calibration_polygons and not self.roi_process_var.get():
            for index, polygon in enumerate(self.calibration_polygons):
                points = []
                for x, y in polygon:
                    points.extend((
                        self.canvas_origin[0] + x * self.zoom,
                        self.canvas_origin[1] + y * self.zoom,
                    ))
                self.image_canvas.create_polygon(
                    *points, outline=COLORS["calibration_overlay"],
                    fill="", width=1,
                    tags="colorchecker",
                )
                center_x = sum(point[0] for point in polygon) / len(polygon)
                center_y = sum(point[1] for point in polygon) / len(polygon)
                self.image_canvas.create_text(
                    self.canvas_origin[0] + center_x * self.zoom,
                    self.canvas_origin[1] + center_y * self.zoom,
                    text=str(index + 1),
                    fill=COLORS["calibration_overlay"],
                    font=FONTS["small"], tags="colorchecker",
                )
        self.zoom_label.configure(text=f"{self.zoom * 100:.0f}%")
        self.display_transform = (
            self.canvas_origin[0], self.canvas_origin[1], self.zoom, image_w, image_h
        )

    def _on_canvas_resize(self) -> None:
        if self.canvas_resize_after:
            try:
                self.root.after_cancel(self.canvas_resize_after)
            except tk.TclError:
                pass
        self.canvas_resize_after = self.root.after(
            50, self._finish_canvas_resize
        )

    def _finish_canvas_resize(self) -> None:
        self.canvas_resize_after = None
        if self.fit_mode:
            self._render_canvas_image()

    def _on_mouse_wheel(self, event) -> None:
        self._zoom_at(event.x, event.y, 1.15 if event.delta > 0 else 1 / 1.15)

    def _zoom_at(self, x: int, y: int, factor: float) -> None:
        old = self.zoom
        new = max(0.05, min(16.0, old * factor))
        if abs(new - old) < 1e-6:
            return
        self.fit_mode = False
        image_x = (x - self.canvas_origin[0]) / old
        image_y = (y - self.canvas_origin[1]) / old
        self.canvas_origin = [x - image_x * new, y - image_y * new]
        self.zoom = new
        self._render_canvas_image()

    def _start_pan(self, event) -> None:
        self.pan_start = (event.x, event.y)

    def _pan(self, event) -> None:
        if self.pan_start is None:
            return
        dx, dy = event.x - self.pan_start[0], event.y - self.pan_start[1]
        self.pan_start = (event.x, event.y)
        self.canvas_origin[0] += dx
        self.canvas_origin[1] += dy
        self.fit_mode = False
        self._schedule_canvas_render()

    def _schedule_canvas_render(self) -> None:
        if self.canvas_overlay_after is not None:
            return
        self.canvas_overlay_after = self.root.after(
            33, self._finish_canvas_render
        )

    def _finish_canvas_render(self) -> None:
        self.canvas_overlay_after = None
        self._render_canvas_image()

    def fit_image(self) -> None:
        self.fit_mode = True
        self._render_canvas_image()

    def actual_size(self) -> None:
        self.fit_mode = False
        self.zoom = 1.0
        if self.display_array is not None:
            canvas_w = self.image_canvas.winfo_width()
            canvas_h = self.image_canvas.winfo_height()
            h, w = self.display_array.shape[:2]
            self.canvas_origin = [(canvas_w - w) / 2, (canvas_h - h) / 2]
        self._render_canvas_image()

    def _canvas_to_image(self, canvas_x: int, canvas_y: int) -> Optional[Tuple[int, int]]:
        origin_x, origin_y, zoom, width, height = self.display_transform
        x = int((canvas_x - origin_x) / max(zoom, 1e-9))
        y = int((canvas_y - origin_y) / max(zoom, 1e-9))
        if 0 <= x < width and 0 <= y < height:
            return x, y
        return None

    def _display_to_source_point(self, point: Tuple[int, int]) -> Tuple[int, int]:
        x, y = point
        if self.roi_process_var.get() and self.roi is not None:
            return x + self.roi.x, y + self.roi.y
        return x, y

    def _roi_index_at(self, point: Tuple[int, int]) -> int:
        x, y = point
        for index in range(len(self.rois) - 1, -1, -1):
            roi = self.rois[index]
            if roi.x <= x < roi.x2 and roi.y <= y < roi.y2:
                return index
        return -1

    def _roi_handle_at(self, point: Tuple[int, int]) -> str:
        if self.roi is None:
            return ""
        tolerance = max(2, round(7 / max(self.zoom, 0.05)))
        x, y = point
        roi = self.roi
        positions = {
            "nw": (roi.x, roi.y),
            "n": ((roi.x + roi.x2) // 2, roi.y),
            "ne": (roi.x2, roi.y),
            "e": (roi.x2, (roi.y + roi.y2) // 2),
            "se": (roi.x2, roi.y2),
            "s": ((roi.x + roi.x2) // 2, roi.y2),
            "sw": (roi.x, roi.y2),
            "w": (roi.x, (roi.y + roi.y2) // 2),
        }
        for name, (handle_x, handle_y) in positions.items():
            if (
                abs(x - handle_x) <= tolerance
                and abs(y - handle_y) <= tolerance
            ):
                return name
        return ""

    def _on_left_press(self, event) -> None:
        if self.gray_pick_mode:
            self._on_canvas_click(event)
            return
        point = self._canvas_to_image(event.x, event.y)
        if point is None:
            return
        if self.roi_mode_var.get():
            if self.roi_process_var.get():
                self.roi_process_var.set(False)
                self.schedule_process(immediate=True)
                return
            source_point = self._display_to_source_point(point)
            self.roi_drag_start = source_point
            handle = self._roi_handle_at(source_point)
            if handle:
                self.roi_drag_mode = "resize"
                self.roi_resize_handle = handle
                self.roi_drag_original = self.roi
                return
            selected = self._roi_index_at(source_point)
            if selected >= 0:
                self.active_roi_index = selected
                self.roi = self.rois[selected]
                self.roi_drag_mode = "move"
                self.roi_drag_original = self.roi
            else:
                if len(self.rois) >= 24:
                    self.roi_drag_start = None
                    self.toast.show(
                        "ROI 数量已达到 24 个，请先删除一个框",
                        "warning",
                    )
                    return
                self.roi_drag_mode = "new"
                self.roi_drag_original = None
                self.roi = None
                self.active_roi_index = -1
            self._update_roi_label()
            self._schedule_canvas_render()
            return
        if self.compare_var.get() and self._current_result_index() > 0:
            self.compare_dragging = True
            self._update_compare_position(event.x)

    def _on_left_drag(self, event) -> None:
        if self.compare_dragging:
            self._update_compare_position(event.x)
            return
        if self.roi_drag_start is None or not self.roi_mode_var.get():
            return
        point = self._canvas_to_image(event.x, event.y)
        if point is None:
            return
        current = self._display_to_source_point(point)
        image_h, image_w = self.preview_image.shape[:2]
        if self.roi_drag_mode == "move" and self.roi_drag_original is not None:
            dx = current[0] - self.roi_drag_start[0]
            dy = current[1] - self.roi_drag_start[1]
            x = min(max(self.roi_drag_original.x + dx, 0), image_w - self.roi_drag_original.width)
            y = min(max(self.roi_drag_original.y + dy, 0), image_h - self.roi_drag_original.height)
            self.roi = ImageROI(x, y, self.roi_drag_original.width, self.roi_drag_original.height)
        elif self.roi_drag_mode == "resize" and self.roi_drag_original is not None:
            original = self.roi_drag_original
            x0, y0, x1, y1 = (
                original.x, original.y, original.x2, original.y2
            )
            handle = self.roi_resize_handle
            if "w" in handle:
                x0 = min(current[0], x1 - 1)
            if "e" in handle:
                x1 = max(current[0] + 1, x0 + 1)
            if "n" in handle:
                y0 = min(current[1], y1 - 1)
            if "s" in handle:
                y1 = max(current[1] + 1, y0 + 1)
            self.roi = clamp_roi(
                ImageROI(x0, y0, x1 - x0, y1 - y0),
                self.preview_image.shape,
            )
        else:
            x0, x1 = sorted((self.roi_drag_start[0], current[0]))
            y0, y1 = sorted((self.roi_drag_start[1], current[1]))
            x1 = min(x1 + 1, image_w)
            y1 = min(y1 + 1, image_h)
            if x1 > x0 and y1 > y0:
                self.roi = ImageROI(x0, y0, x1 - x0, y1 - y0)
                if self.active_roi_index < 0:
                    self.rois.append(self.roi)
                    self.active_roi_index = len(self.rois) - 1
        self._sync_active_roi_to_list()
        self._update_roi_label()
        self._schedule_canvas_render()

    def _on_left_release(self, _event) -> None:
        if self.compare_dragging:
            self.compare_dragging = False
            return
        if self.roi_drag_start is None:
            return
        self.roi_drag_start = None
        self.roi_drag_original = None
        self.roi_drag_mode = ""
        self.roi_resize_handle = ""
        if self.roi is not None:
            try:
                if self.loaded.domain == "bayer":
                    self.roi = self.roi.align_for_bayer(self.preview_image.shape)
                else:
                    self.roi.validate(self.preview_image.shape)
            except ISPError:
                if 0 <= self.active_roi_index < len(self.rois):
                    self.rois.pop(self.active_roi_index)
                self.roi = None
                self.active_roi_index = -1
            self._sync_active_roi_to_list()
        self._update_roi_label()
        if self.roi_process_var.get():
            self.schedule_process(immediate=True)
        else:
            self.render_current(schedule_analysis=True)

    def _update_compare_position(self, canvas_x: int) -> None:
        origin_x, _origin_y, zoom, width, _height = self.display_transform
        image_x = (canvas_x - origin_x) / max(zoom, 1e-9)
        self.compare_position = float(np.clip(image_x / max(width, 1), 0.0, 1.0))
        self._schedule_view_render()

    def _schedule_view_render(self) -> None:
        if self.view_render_after is not None:
            return
        self.view_render_after = self.root.after(
            33, self._finish_view_render
        )

    def _finish_view_render(self) -> None:
        self.view_render_after = None
        self.render_current(schedule_analysis=False)

    def _roi_mode_changed(self) -> None:
        if self.roi_mode_var.get() and self.roi_process_var.get():
            self.roi_process_var.set(False)
            self.schedule_process(immediate=True)
        self.image_canvas.configure(
            cursor="crosshair" if self.roi_mode_var.get() else "arrow"
        )
        self.render_current(schedule_analysis=False)

    def _roi_processing_changed(self) -> None:
        if self.roi_process_var.get() and self.roi is None:
            self.roi_process_var.set(False)
            self.toast.show("请先在图像上框选 ROI", "warning")
            return
        self.roi_mode_var.set(False)
        self.fit_mode = True
        self.schedule_process(immediate=True)

    def clear_roi(self) -> None:
        was_processing = self.roi_process_var.get()
        self.rois = []
        self.active_roi_index = -1
        self.roi = None
        self.roi_process_var.set(False)
        self._update_roi_label()
        if was_processing:
            self.schedule_process(immediate=True)
        else:
            self.render_current(schedule_analysis=True)

    def delete_active_roi(self) -> None:
        if not (
            0 <= self.active_roi_index < len(self.rois)
        ):
            return
        was_processing = self.roi_process_var.get()
        self.rois.pop(self.active_roi_index)
        self.active_roi_index = min(
            self.active_roi_index, len(self.rois) - 1
        )
        self.roi = (
            self.rois[self.active_roi_index]
            if self.active_roi_index >= 0 else None
        )
        if self.roi is None:
            self.roi_process_var.set(False)
        self._update_roi_label()
        if was_processing:
            self.schedule_process(immediate=True)
        else:
            self.render_current(schedule_analysis=True)

    def generate_24_rois(
        self, rows: int = 4, cols: int = 6
    ) -> None:
        if self.roi is None:
            self.toast.show(
                "请先框选色卡或采样区域的外接矩形", "warning"
            )
            return
        self.rois = generate_grid_rois(
            self.roi,
            self.preview_image.shape,
            rows=rows,
            cols=cols,
            bayer_aligned=self.loaded.domain == "bayer",
        )
        self.active_roi_index = 0
        self.roi = self.rois[0]
        self.roi_process_var.set(False)
        self._update_roi_label()
        self.render_current(schedule_analysis=True)
        self.toast.show(
            f"已生成 {rows}×{cols} 色块 ROI；"
            "可拖动边框控制点或打开 ROI 管理器微调",
            "success",
        )

    def _roi_editor_changed(
        self, rois: List[ImageROI], active_index: int
    ) -> None:
        self.rois = list(rois[:24])
        self.active_roi_index = (
            min(max(active_index, 0), len(self.rois) - 1)
            if self.rois else -1
        )
        self.roi = (
            self.rois[self.active_roi_index]
            if self.active_roi_index >= 0 else None
        )
        if self.roi is None:
            self.roi_process_var.set(False)
        self._update_roi_label()
        if self.roi_process_var.get():
            self.schedule_process(immediate=True)
        else:
            self.render_current(schedule_analysis=True)

    def open_roi_editor(self) -> None:
        self._sync_active_roi_to_list()
        if self.roi_editor is not None and self.roi_editor.winfo_exists():
            self.roi_editor.lift()
            return
        self.roi_editor = ROIEditor(
            self.root,
            self.rois,
            self.active_roi_index,
            self.preview_image.shape,
            self.loaded.domain == "bayer",
            self._roi_editor_changed,
        )

    def _nudge_active_roi(self, event, dx: int, dy: int):
        if (
            self._is_text_input(event.widget)
            or not self.roi_mode_var.get()
            or self.roi is None
        ):
            return
        resize = bool(event.state & 0x0001)
        roi = self.roi
        candidate = (
            ImageROI(
                roi.x,
                roi.y,
                roi.width + dx * 2,
                roi.height + dy * 2,
            )
            if resize
            else ImageROI(
                roi.x + dx,
                roi.y + dy,
                roi.width,
                roi.height,
            )
        )
        self.roi = clamp_roi(
            candidate,
            self.preview_image.shape,
            bayer_aligned=self.loaded.domain == "bayer",
        )
        self._sync_active_roi_to_list()
        self._update_roi_label()
        if self.roi_process_var.get():
            self.schedule_process(immediate=True)
        else:
            self.render_current(schedule_analysis=True)
        return "break"

    def _update_roi_label(self) -> None:
        if self.roi is None:
            self.roi_label.configure(
                text=(
                    f"ROI: {len(self.rois)} boxes · none selected"
                    if self.rois else "ROI: Full frame"
                )
            )
        else:
            self.roi_label.configure(
                text=(
                    f"ROI {self.active_roi_index + 1}/{len(self.rois)}: "
                    f"x={self.roi.x}, y={self.roi.y}, "
                    f"{self.roi.width}×{self.roi.height}"
                )
            )

    def _show_temporary_input(self, _event=None) -> None:
        if _event is not None and self._is_text_input(_event.widget):
            return
        if not self.temporary_input:
            self.temporary_input = True
            self.render_current(schedule_analysis=False)

    def _hide_temporary_input(self, _event=None) -> None:
        if self.temporary_input:
            self.temporary_input = False
            self.render_current(schedule_analysis=False)

    def _on_canvas_motion(self, event) -> None:
        now = time.perf_counter()
        if now - self._last_mouse_status_at < (1.0 / 30.0):
            return
        self._last_mouse_status_at = now
        point = self._canvas_to_image(event.x, event.y)
        if point is None or self.display_array is None:
            return
        x, y = point
        source_x, source_y = self._display_to_source_point(point)
        value = self.display_array[y, x]
        self.status_var.set(
            f"x={source_x}, y={source_y} · RGB=({value[0]:.4f}, {value[1]:.4f}, {value[2]:.4f})"
            + (" · 点击此处估算白平衡" if self.gray_pick_mode else "")
        )

    def arm_gray_picker(self) -> None:
        if self.loaded.domain != "bayer":
            self.toast.show("灰点拾取目前只用于 Bayer RAW", "warning")
            return
        if self.compare_var.get():
            self.compare_var.set(False)
            self.render_current()
        self.gray_pick_mode = True
        self.status_var.set("灰点白平衡：请在预览中点击中性灰区域")

    def _on_canvas_click(self, event) -> None:
        if not self.gray_pick_mode:
            return
        point = self._canvas_to_image(event.x, event.y)
        if point is None:
            return
        self.gray_pick_mode = False
        x, y = self._display_to_source_point(point)
        h, w = self.preview_image.shape[:2]
        radius = max(4, min(h, w) // 80)
        x0, x1 = max(0, x - radius), min(w, x + radius + 1)
        y0, y1 = max(0, y - radius), min(h, y + radius + 1)
        # Align ROI boundaries so all four CFA planes have similar counts.
        x0, y0 = x0 // 2 * 2, y0 // 2 * 2
        x1, y1 = x1 // 2 * 2, y1 // 2 * 2
        if x1 <= x0 or y1 <= y0:
            return
        module = self.pipeline.module_by_id("white_balance")
        awb_source = self.preview_image
        if (
            len(self.results) > 2
            and self.results[2].domain == "bayer"
            and self.results[2].image.shape[:2]
            == self.preview_image.shape[:2]
        ):
            awb_source = self.results[2].image
        try:
            result = estimate_awb(
                awb_source,
                self.loaded.metadata,
                method="ROI Neutral",
                roi=ImageROI(x0, y0, x1 - x0, y1 - y0),
                gain_limit=float(module.parameters["gain_limit"]),
            )
        except ISPError as exc:
            self.toast.show(str(exc), "warning")
            return
        module.parameters.update({
            "r_gain": result.r_gain,
            "gr_gain": result.gr_gain,
            "gb_gain": result.gb_gain,
            "b_gain": result.b_gain,
        })
        self._mark_manual_parameter_state(module)
        if self.pipeline.modules[self.selected_module_index].module_id == "white_balance":
            self._build_parameter_editor(module)
            self._refresh_module_state()
        self.schedule_process(immediate=True)
        self.status_var.set(
            f"已从 ROI ({x0},{y0})-({x1},{y1}) 估算 WB："
            f"R {module.parameters['r_gain']:.3f}, "
            f"B {module.parameters['b_gain']:.3f} · "
            f"Confidence {result.confidence * 100:.0f}% · 待应用"
        )

    def _analysis_image(self, result: StageResult) -> np.ndarray:
        if (
            self.roi is not None
            and self.analysis_roi_var.get()
            and not self.roi_process_var.get()
            and result.image.shape[:2] == self.preview_image.shape[:2]
        ):
            ys, xs = self.roi.slices()
            return result.image[ys, xs]
        return result.image

    def _active_analysis_type(self) -> str:
        if not hasattr(self, "analysis_notebook"):
            return "Histogram"
        selected = self.analysis_notebook.select()
        return str(self.analysis_notebook.tab(selected, "text"))

    def _analysis_canvas_resized(self, analysis_type: str) -> None:
        if (
            not self.analysis_collapsed
            and self.results
            and self._active_analysis_type() == analysis_type
        ):
            self.schedule_analysis_refresh()

    def _analysis_roi_key(self, result: StageResult):
        if (
            self.roi is not None
            and self.analysis_roi_var.get()
            and not self.roi_process_var.get()
            and result.image.shape[:2] == self.preview_image.shape[:2]
        ):
            return (
                self.roi.x,
                self.roi.y,
                self.roi.width,
                self.roi.height,
            )
        return None

    def schedule_analysis_refresh(self, delay: int = 220) -> None:
        self.analysis_generation += 1
        generation = self.analysis_generation
        if self.analysis_pending_after is not None:
            try:
                self.root.after_cancel(self.analysis_pending_after)
            except tk.TclError:
                pass
            self.analysis_pending_after = None
            self.performance.increment("dropped_analysis_requests")
        if self.analysis_collapsed or not self.results:
            self.performance.set_value(
                "analysis_state",
                "collapsed" if self.analysis_collapsed else "deferred",
            )
            self._update_performance_status()
            return
        self.performance.set_value("analysis_state", "deferred")
        self._update_performance_status()
        self.analysis_pending_after = self.root.after(
            max(0, int(delay)),
            lambda: self._start_analysis(generation),
        )

    def _start_analysis(self, generation: int) -> None:
        self.analysis_pending_after = None
        if (
            generation != self.analysis_generation
            or self.analysis_collapsed
            or not self.results
        ):
            return
        analysis_type = self._active_analysis_type()
        index = self._current_result_index()
        result = self.results[index]
        roi_key = self._analysis_roi_key(result)
        width = 0
        height = 0
        settings = (self.channel_var.get(),)
        if analysis_type == "Waveform":
            width = max(self.waveform_canvas.winfo_width(), 384)
            height = max(self.waveform_canvas.winfo_height(), 105)
            settings += (self.waveform_mode_var.get(), width, height)
        elif analysis_type == "Vectorscope":
            width = max(self.vectorscope_canvas.winfo_width(), 320)
            height = max(self.vectorscope_canvas.winfo_height(), 105)
            settings += (
                self.vectorscope_mode_var.get(),
                float(self.vectorscope_scale_var.get()),
                width,
                height,
            )
        key = self.render_cache.analysis_key(
            self.result_revision,
            index,
            analysis_type,
            roi_key,
            *settings,
        )
        cached = self.render_cache.get_analysis(key)
        if cached is not None:
            self.performance.increment("analysis_cache_hits")
            self.performance.set_value("analysis_state", "cached")
            self._apply_analysis_payload(
                generation, key, analysis_type, index, cached
            )
            return
        self.performance.increment("analysis_cache_misses")
        if self.analysis_future is not None and not self.analysis_future.done():
            if self.analysis_future.cancel():
                self.performance.increment("dropped_analysis_requests")
        metadata = copy.deepcopy(self.loaded.metadata)
        if (
            analysis_type in {"Histogram", "Waveform", "Vectorscope"}
            or (
                analysis_type == "Statistics"
                and result.domain != "bayer"
            )
        ):
            image = self._stage_rgb(index)
            domain = "rgb"
            if roi_key is not None:
                ys, xs = self.roi.slices()
                image = image[ys, xs]
        else:
            image = self._analysis_image(result)
            domain = result.domain
        image = np.asarray(image, dtype=np.float32)
        mode = (
            self.waveform_mode_var.get()
            if analysis_type == "Waveform"
            else self.vectorscope_mode_var.get()
        )
        scale = float(self.vectorscope_scale_var.get())
        self.performance.set_value("analysis_state", "running")
        self._update_performance_status()
        future = self.analysis_executor.submit(
            self._compute_analysis_payload,
            analysis_type,
            image,
            domain,
            metadata,
            mode,
            scale,
            width,
            height,
        )
        self.analysis_future = future
        self._schedule_analysis_poll(
            future, generation, key, analysis_type, index
        )

    @staticmethod
    def _compute_analysis_payload(
        analysis_type: str,
        image: np.ndarray,
        domain: str,
        metadata: RawMetadata,
        mode: str,
        scale: float,
        width: int,
        height: int,
    ):
        started = time.perf_counter()
        if analysis_type == "Histogram":
            value = compute_histogram(image, domain, metadata)
        elif analysis_type == "Waveform":
            value = compute_waveform(
                image,
                domain,
                metadata,
                mode=mode,
                width=width,
                height=height,
            )
        elif analysis_type == "Vectorscope":
            size = max(128, min(width, max(height, 220)))
            value = compute_vectorscope(
                image,
                domain,
                metadata,
                mode=mode,
                size=size,
                saturation_scale=scale,
            )
        else:
            value = compute_statistics(image, domain, metadata)
        elapsed = (time.perf_counter() - started) * 1000.0
        return {"value": value, "elapsed_ms": elapsed}

    def _schedule_analysis_poll(
        self,
        future: Future,
        generation: int,
        key,
        analysis_type: str,
        index: int,
    ) -> None:
        after_id: Optional[str] = None

        def poll() -> None:
            if after_id is not None:
                self.analysis_poll_after_ids.discard(after_id)
            if not future.done():
                self._schedule_analysis_poll(
                    future, generation, key, analysis_type, index
                )
                return
            if future.cancelled():
                return
            try:
                payload = future.result()
            except Exception as exc:
                if generation == self.analysis_generation:
                    self.performance.set_value("analysis_state", "failed")
                    self.module_diagnostics_var.set(
                        f"Analysis failed: {exc}"
                    )
                    self._update_performance_status()
                return
            self.render_cache.put_analysis(key, payload)
            if generation != self.analysis_generation:
                self.performance.increment("dropped_analysis_results")
                return
            self._apply_analysis_payload(
                generation, key, analysis_type, index, payload
            )

        after_id = self.root.after(15, poll)
        self.analysis_poll_after_ids.add(after_id)

    def _apply_analysis_payload(
        self,
        generation: int,
        key,
        analysis_type: str,
        index: int,
        payload,
    ) -> None:
        if (
            generation != self.analysis_generation
            or self.analysis_collapsed
            or analysis_type != self._active_analysis_type()
            or index != self._current_result_index()
        ):
            return
        self._last_analysis_payload = (key, analysis_type, payload)
        self.performance.record("analysis", payload["elapsed_ms"])
        self.performance.set_value("analysis_state", "ready")
        value = payload["value"]
        if analysis_type == "Histogram":
            self._render_histogram(value)
        elif analysis_type == "Waveform":
            self._render_waveform(value)
        elif analysis_type == "Vectorscope":
            self._render_vectorscope(value)
        else:
            self._render_statistics(value)
        self._update_performance_status()

    def _refresh_analysis(self) -> None:
        self.schedule_analysis_refresh(0)

    def _draw_histogram(self) -> None:
        self.schedule_analysis_refresh(0)

    def _render_histogram(self, hist) -> None:
        self.hist_canvas.delete("all")
        width = max(self.hist_canvas.winfo_width(), 256)
        height = max(self.hist_canvas.winfo_height(), 80)
        colors = {
            "R": COLORS["channel_r"], "G": COLORS["channel_g"],
            "B": COLORS["channel_b"], "Y": COLORS["channel_y"],
        }
        for key in ("Y", "R", "G", "B"):
            values = np.log1p(hist[key].astype(np.float64))
            values /= max(values.max(initial=1.0), 1e-9)
            points = []
            for index, value in enumerate(values):
                points.extend((index / 255 * (width - 1), height - 2 - value * (height - 8)))
            self.hist_canvas.create_line(
                *points, fill=colors[key], width=2 if key == "Y" else 1
            )
        self.hist_canvas.create_text(
            8, 7, text="HISTOGRAM  Y / R / G / B", anchor="nw",
            fill=MUTED, font=FONTS["small"],
        )

    def _draw_waveform(self) -> None:
        self.schedule_analysis_refresh(0)

    def _render_waveform(self, waveform: np.ndarray) -> None:
        self.waveform_canvas.delete("all")
        width = max(self.waveform_canvas.winfo_width(), 384)
        height = max(self.waveform_canvas.winfo_height(), 105)
        array8 = np.round(np.clip(waveform, 0, 1) * 255).astype(np.uint8)
        pil = Image.fromarray(array8)
        self.waveform_photo = ImageTk.PhotoImage(pil)
        self.waveform_canvas.create_image(0, 0, image=self.waveform_photo, anchor="nw")
        for fraction in (0.25, 0.5, 0.75):
            y = height - fraction * height
            self.waveform_canvas.create_line(
                0, y, width, y, fill=COLORS["scope_grid"],
                dash=(3, 3),
            )
        maximum_dn = (1 << int(self.loaded.metadata.bit_depth)) - 1
        self.waveform_canvas.create_text(
            6, 5,
            text=f"{self.waveform_mode_var.get()} · 0…{maximum_dn} DN",
            anchor="nw", fill=COLORS["channel_y"],
            font=FONTS["small"],
        )

    def _draw_vectorscope(self) -> None:
        self.schedule_analysis_refresh(0)

    def _render_vectorscope(self, scope: np.ndarray) -> None:
        self.vectorscope_canvas.delete("all")
        canvas_w = max(self.vectorscope_canvas.winfo_width(), 320)
        canvas_h = max(self.vectorscope_canvas.winfo_height(), 105)
        size = scope.shape[0]
        pil = Image.fromarray(
            np.round(np.clip(scope, 0, 1) * 255).astype(np.uint8)
        )
        display_size = min(canvas_h, canvas_w, size)
        pil = pil.resize((display_size, display_size), Image.Resampling.LANCZOS)
        self.vectorscope_photo = ImageTk.PhotoImage(pil)
        self.vectorscope_canvas.create_image(
            canvas_w / 2, canvas_h / 2,
            image=self.vectorscope_photo, anchor="center",
        )
        self.vectorscope_canvas.create_text(
            6, 5, text=self.vectorscope_mode_var.get(),
            anchor="nw", fill=COLORS["channel_y"],
            font=FONTS["small"],
        )

    def _update_metrics(self) -> None:
        self.schedule_analysis_refresh(0)

    def _render_statistics(self, stats) -> None:
        result = self.results[self._current_result_index()]
        lines = [
            f"Stage: {result.name}   Domain: {result.domain.upper()}",
            f"Time: {result.elapsed_ms:.2f} ms   Range: {float(result.image.min()):.4f} … {float(result.image.max()):.4f}",
            (
                f"Clipped: high {stats['clipped_high'] * 100:.3f}%   "
                f"low {stats['clipped_low'] * 100:.3f}%   "
                f"range {stats['range_usage'] * 100:.2f}%"
            ),
        ]
        channel_text = "  ·  ".join(
            (
                f"{name} μ {values['mean']:.4f}  med {values['median']:.4f}  "
                f"σ {values['std']:.4f}"
            )
            for name, values in stats["channels"].items()
        )
        lines.append(channel_text)
        if result.diagnostics:
            detail = "  ·  ".join(
                f"{key}: {self._format_value(value)}"
                for key, value in list(result.diagnostics.items())[:4]
            )
            lines.append(detail)
        self.metrics_label.configure(text="\n".join(lines))
        self.module_diagnostics_var.set(
            f"{result.domain.upper()} · {result.elapsed_ms:.2f} ms · "
            f"clip H {stats['clipped_high'] * 100:.3f}% / "
            f"L {stats['clipped_low'] * 100:.3f}%"
        )

    def _update_performance_status(self) -> None:
        counters = self.render_cache.counters()
        self.performance.set_value(
            "display_cache",
            f"{counters['stage_hits']}/"
            f"{counters['stage_hits'] + counters['stage_misses']}",
        )
        self.performance.set_value(
            "analysis_cache",
            f"{counters['analysis_hits']}/"
            f"{counters['analysis_hits'] + counters['analysis_misses']}",
        )
        if hasattr(self, "performance_status_var"):
            self.performance_status_var.set(self.performance.status_text())
        if (
            self.performance_window is not None
            and self.performance_window.winfo_exists()
            and self.performance_text is not None
        ):
            self.performance_text.configure(state="normal")
            self.performance_text.delete("1.0", "end")
            self.performance_text.insert("1.0", self.performance.details_text())
            self.performance_text.configure(state="disabled")

    def show_performance_details(self) -> None:
        if (
            self.performance_window is not None
            and self.performance_window.winfo_exists()
        ):
            self.performance_window.lift()
            self.performance_window.focus_set()
            self._update_performance_status()
            return
        window = tk.Toplevel(self.root)
        window.title("Performance Details")
        window.geometry("650x430")
        window.minsize(480, 300)
        window.configure(bg=BG)
        self.performance_window = window
        self.performance_details_visible = True
        text = tk.Text(
            window,
            bg=COLORS["canvas_alt"],
            fg=FG,
            insertbackground=FG,
            relief="flat",
            wrap="none",
            font=FONTS["mono"],
            padx=12,
            pady=10,
        )
        text.pack(fill="both", expand=True, padx=10, pady=10)
        self.performance_text = text
        self.wheel_router.register(text, text)

        def close_window() -> None:
            self.performance_details_visible = False
            self.performance_window = None
            self.performance_text = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_window)
        self._update_performance_status()

    def _apply_ui_scale_from_menu(self) -> None:
        scale = UI_SCALE_CHOICES.get(self.ui_scale_var.get(), 1.0)
        self.ui_scale = float(scale)
        configure_theme(self.root, self.ui_scale)
        self._raster_key = None
        self._render_canvas_image()
        self.toast.show(
            f"UI scale: {self.ui_scale_var.get()}", "info"
        )

    def open_calibration_workspace(self) -> None:
        if (
            self.calibration_workspace is not None
            and self.calibration_workspace.winfo_exists()
        ):
            self.calibration_workspace.lift()
            self.calibration_workspace.focus_set()
            self._refresh_auto_summary()
            return
        self.calibration_workspace = CalibrationWorkspace(self.root, self)
        self._refresh_auto_summary()

    @staticmethod
    def _image_filetypes():
        return [
            (
                "所有支持格式",
                "*.raw *.bin *.dat *.dng *.nef *.cr2 *.cr3 *.arw "
                "*.raf *.rw2 *.orf *.png *.jpg *.jpeg *.tif *.tiff",
            ),
            ("裸 RAW", "*.raw *.bin *.dat"),
            (
                "相机 RAW",
                "*.dng *.nef *.cr2 *.cr3 *.arw *.raf *.rw2 *.orf",
            ),
            ("图像", "*.png *.jpg *.jpeg *.tif *.tiff"),
            ("所有文件", "*.*"),
        ]

    def _refresh_image_selector(self) -> None:
        if not hasattr(self, "image_combo"):
            return
        labels = [
            f"{index + 1}/{len(self.work_items)} · {item.label}"
            for index, item in enumerate(self.work_items)
        ]
        self.image_combo["values"] = labels
        if labels:
            index = min(
                max(self.current_image_index, 0), len(labels) - 1
            )
            self.image_combo.current(index)

    def _sync_active_roi_to_list(self) -> None:
        if self.roi is None:
            return
        if 0 <= self.active_roi_index < len(self.rois):
            self.rois[self.active_roi_index] = self.roi
        elif len(self.rois) < 24:
            self.rois.append(self.roi)
            self.active_roi_index = len(self.rois) - 1

    def _store_current_work_item(self) -> None:
        if not (
            0 <= self.current_image_index < len(self.work_items)
        ):
            return
        self._sync_active_roi_to_list()
        item = self.work_items[self.current_image_index]
        item.loaded = self.loaded
        item.pipeline_snapshot = copy.deepcopy(
            self.pipeline.snapshot()
        )
        item.calibration_session = copy.deepcopy(
            self.calibration_session
        )
        item.rois = list(self.rois)
        item.active_roi_index = self.active_roi_index
        item.manual_parameter_snapshots = copy.deepcopy(
            self.manual_parameter_snapshots
        )
        item.manual_dirty_modules = sorted(
            self.manual_dirty_modules
        )

    def _activate_work_item(self, index: int) -> None:
        if not (0 <= index < len(self.work_items)):
            return
        if index == self.current_image_index and self.loaded is (
            self.work_items[index].loaded
        ):
            self._refresh_image_selector()
            return
        if (
            self.calibration_workspace is not None
            and self.calibration_workspace.winfo_exists()
        ):
            self.calibration_workspace.close()
        self._store_current_work_item()
        if self.roi_editor is not None and self.roi_editor.winfo_exists():
            self.roi_editor.destroy()
        item = self.work_items[index]
        self.current_image_index = index
        self.loaded = item.loaded
        self.pipeline.load_snapshot(
            copy.deepcopy(item.pipeline_snapshot)
        )
        self.calibration_session = copy.deepcopy(
            item.calibration_session
        )
        self.rois = list(item.rois)
        self.active_roi_index = item.active_roi_index
        self.roi = item.active_roi()
        self.calibration_polygons = []
        self.roi_process_var.set(False)
        self.input_revision += 1
        self.pipeline_cache = {}
        self.render_cache.clear()
        self._prepare_preview()
        self.results = []
        self.fit_mode = True
        if item.manual_parameter_snapshots:
            self.manual_parameter_snapshots = copy.deepcopy(
                item.manual_parameter_snapshots
            )
            for module in self.pipeline.modules:
                self.manual_parameter_snapshots.setdefault(
                    module.module_id,
                    self._module_edit_snapshot(module),
                )
            self.manual_dirty_modules = set(
                item.manual_dirty_modules
            )
            self._update_manual_action_state()
        else:
            self._reset_manual_parameter_snapshots()
        self._refresh_image_selector()
        self._refresh_pipeline_list()
        self._build_parameter_editor(
            self.pipeline.modules[self.selected_module_index]
        )
        self._update_roi_label()
        self._set_loaded_status()
        self.schedule_process(immediate=True)

    def _on_image_selected(self, _event=None) -> None:
        index = self.image_combo.current()
        if index >= 0:
            self._activate_work_item(index)

    def _load_paths(self, paths) -> None:
        paths = [str(path) for path in paths if path]
        if not paths:
            return
        plain_paths = [
            path
            for path in paths
            if Path(path).suffix.lower() in PLAIN_EXTENSIONS
        ]
        metadata = None
        if plain_paths:
            title = (
                "裸 RAW 元数据（应用到本次选择的全部裸 RAW）"
                if len(plain_paths) > 1
                else "裸 RAW 元数据"
            )
            metadata = ask_raw_metadata(
                self.root, copy.deepcopy(self.loaded.metadata), title
            )
            if metadata is None:
                return
        base_snapshot = copy.deepcopy(self.pipeline.snapshot())
        if len(paths) > 1:
            self.import_generation += 1
            generation = self.import_generation
            self.status_var.set(
                f"正在后台导入 {len(paths)} 张图像…"
            )
            self.import_future = self.io_executor.submit(
                self._read_work_items,
                paths,
                metadata,
                base_snapshot,
            )
            self._poll_image_import(
                self.import_future, generation, paths
            )
            return
        new_items, failures = self._read_work_items(
            paths, metadata, base_snapshot
        )
        self._finish_image_import(paths, new_items, failures)

    @staticmethod
    def _read_work_items(paths, metadata, base_snapshot):
        new_items: List[ImageWorkItem] = []
        failures = []
        for path in paths:
            try:
                item_metadata = (
                    copy.deepcopy(metadata)
                    if Path(path).suffix.lower() in PLAIN_EXTENSIONS
                    else None
                )
                loaded = load_image(path, item_metadata)
                session = CalibrationSession(
                    name=f"{Path(path).stem} Calibration",
                    raw_metadata=copy.deepcopy(loaded.metadata),
                )
                new_items.append(
                    ImageWorkItem(
                        loaded,
                        snapshot_for_image(base_snapshot, loaded),
                        session,
                    )
                )
            except Exception as exc:
                failures.append(f"{Path(path).name}: {exc}")
        return new_items, failures

    def _poll_image_import(
        self, future: Future, generation: int, paths
    ) -> None:
        if generation != self.import_generation:
            return
        if not future.done():
            self.import_poll_after = self.root.after(
                40,
                lambda: self._poll_image_import(
                    future, generation, paths
                ),
            )
            return
        self.import_poll_after = None
        try:
            new_items, failures = future.result()
        except Exception as exc:
            new_items, failures = [], [str(exc)]
        self.import_future = None
        if generation != self.import_generation:
            return
        self._finish_image_import(paths, new_items, failures)

    def _finish_image_import(
        self, paths, new_items, failures
    ) -> None:
        if not new_items:
            messagebox.showerror(
                "导入失败",
                "\n".join(failures[:12]) or "没有可导入的图像",
                parent=self.root,
            )
            return
        self._store_current_work_item()
        replace_placeholder = (
            len(self.work_items) == 1
            and self.work_items[0].loaded.source_path is None
            and self.work_items[0].loaded.description
            == "内置合成 Bayer 测试图"
        )
        if replace_placeholder:
            self.work_items = new_items
            target_index = 0
            self.current_image_index = -1
        else:
            target_index = len(self.work_items)
            self.work_items.extend(new_items)
        self.last_directory = str(Path(paths[0]).parent)
        self._refresh_image_selector()
        self._activate_work_item(target_index)
        message = f"已导入 {len(new_items)} 张图像"
        if failures:
            message += f"，{len(failures)} 张失败"
            messagebox.showwarning(
                "部分图像未导入",
                "\n".join(failures[:12]),
                parent=self.root,
            )
        self.toast.show(message, "success" if not failures else "warning")

    def open_files(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="导入一张或多张 RAW / 图像",
            initialdir=self.last_directory or None,
            filetypes=self._image_filetypes(),
        )
        self._load_paths(paths)

    def open_file(self) -> None:
        """Compatibility entry point for integrations that open one file."""

        path = filedialog.askopenfilename(
            parent=self.root,
            title="打开 RAW 或图像",
            initialdir=self.last_directory or None,
            filetypes=self._image_filetypes(),
        )
        self._load_paths((path,) if path else ())

    def edit_raw_metadata(self) -> None:
        metadata = ask_raw_metadata(
            self.root, copy.deepcopy(self.loaded.metadata), "查看 / 编辑 RAW 元数据"
        )
        if metadata is None:
            return
        if self.loaded.source_path and self.loaded.source_path.suffix.lower() in PLAIN_EXTENSIONS:
            try:
                self.loaded = load_image(str(self.loaded.source_path), metadata)
            except Exception as exc:
                messagebox.showerror("重新读取失败", str(exc), parent=self.root)
                return
        else:
            if metadata.width != self.loaded.image.shape[1] or metadata.height != self.loaded.image.shape[0]:
                messagebox.showwarning(
                    "尺寸未应用",
                    "当前不是裸 RAW 文件，宽高由图像本身决定；其他元数据仍会应用。",
                    parent=self.root,
                )
                metadata.width = self.loaded.image.shape[1]
                metadata.height = self.loaded.image.shape[0]
            self.loaded.metadata = metadata
        self.input_revision += 1
        self._sync_blc_to_metadata()
        self._prepare_preview()
        self._reset_manual_parameter_snapshots()
        self._store_current_work_item()
        self._build_parameter_editor(self.pipeline.modules[self.selected_module_index])
        self.schedule_process(immediate=True)

    def _set_loaded_status(self) -> None:
        meta = self.loaded.metadata
        self.status_var.set(
            f"Image {self.current_image_index + 1}/{len(self.work_items)} · "
            f"{self.loaded.description} · {meta.width}×{meta.height} · "
            f"{meta.bit_depth} bit · {meta.bayer_pattern}"
        )

    def save_pipeline_config(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.root, title="保存 ISP 配置",
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialdir=self.last_directory or None,
        )
        if not path:
            return
        try:
            self._sync_active_roi_to_list()
            ui_state = {
                "stage_index": self.stage_combo.current(),
                "channel": self.channel_var.get(),
                "artifact": self.artifact_var.get(),
                "artifact_overlay": self.artifact_overlay_var.get(),
                "compare": self.compare_var.get(),
                "compare_position": self.compare_position,
                "clipping": self.clipping_var.get(),
                "roi": self.roi.to_dict() if self.roi else None,
                "rois": [roi.to_dict() for roi in self.rois],
                "active_roi_index": self.active_roi_index,
                "process_roi": self.roi_process_var.get(),
                "analyze_roi": self.analysis_roi_var.get(),
                "waveform_mode": self.waveform_mode_var.get(),
                "vectorscope_mode": self.vectorscope_mode_var.get(),
                "vectorscope_scale": self.vectorscope_scale_var.get(),
                "selected_module_index": self.selected_module_index,
                "window_geometry": self.root.geometry(),
                "analysis_collapsed": self.analysis_collapsed,
                "analysis_selected_tab": self._active_analysis_type(),
                "expert_mode": self.expert_mode,
                "advanced_parameters": dict(
                    self.advanced_param_state
                ),
                "performance_details_visible": (
                    self.performance_window is not None
                    and self.performance_window.winfo_exists()
                ),
                "ui_scale": self.ui_scale,
                "ui_scale_mode": self.ui_scale_var.get(),
                "fit_mode": self.fit_mode,
                "zoom": self.zoom,
                "last_directory": str(Path(path).parent),
                "main_sashes": [
                    self.main_paned.sashpos(index)
                    for index in range(
                        max(0, len(self.main_paned.panes()) - 1)
                    )
                ],
            }
            if (
                self.calibration_workspace is not None
                and self.calibration_workspace.winfo_exists()
            ):
                self.calibration_workspace.sync_session()
                ui_state["calibration"] = (
                    self.calibration_workspace.get_ui_state()
                )
            elif isinstance(
                self.loaded_ui_state.get("calibration"), dict
            ):
                ui_state["calibration"] = copy.deepcopy(
                    self.loaded_ui_state["calibration"]
                )
            self.calibration_session.raw_metadata = copy.deepcopy(self.loaded.metadata)
            lsc_module = self.pipeline.module_by_id("lens_shading_correction")
            if lsc_module.mesh is not None:
                self.calibration_session.lsc_mesh = lsc_module.mesh.copy()
            save_config(
                path,
                self.loaded.metadata,
                self.pipeline,
                ui_state=ui_state,
                calibration=self.calibration_session,
            )
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return
        self.last_directory = str(Path(path).parent)
        self.loaded_ui_state = copy.deepcopy(ui_state)
        self._store_current_work_item()
        self.toast.show("ISP 配置已保存", "success")
        self.status_var.set(f"配置已保存：{path}")

    def load_pipeline_config(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="加载 ISP 配置",
            filetypes=[("JSON", "*.json")],
            initialdir=self.last_directory or None,
        )
        if not path:
            return
        try:
            data = load_config(path)
            if (
                self.calibration_workspace is not None
                and self.calibration_workspace.winfo_exists()
            ):
                self.calibration_workspace.close()
            warnings = self.pipeline.load_snapshot(data.get("pipeline", []))
            if data.get("raw"):
                loaded_meta = RawMetadata.from_dict(data["raw"])
                # Keep real dimensions unless a plain RAW can be re-read.
                if not (
                    self.loaded.source_path
                    and self.loaded.source_path.suffix.lower() in PLAIN_EXTENSIONS
                ):
                    loaded_meta.width = self.loaded.image.shape[1]
                    loaded_meta.height = self.loaded.image.shape[0]
                self.loaded.metadata = loaded_meta
                self.input_revision += 1
            if data.get("calibration"):
                self.calibration_session = CalibrationSession.from_dict(
                    data["calibration"]
                )
                if self.calibration_session.lsc_mesh is not None:
                    lsc_module = self.pipeline.module_by_id("lens_shading_correction")
                    if lsc_module.mesh is None:
                        lsc_module.set_mesh(self.calibration_session.lsc_mesh)
            ui_state = data.get("ui_state", {})
            self.loaded_ui_state = copy.deepcopy(ui_state)
            self.last_directory = str(
                ui_state.get("last_directory") or Path(path).parent
            )
            rois_data = ui_state.get("rois")
            if isinstance(rois_data, list):
                self.rois = [
                    ImageROI.from_dict(item)
                    for item in rois_data[:24]
                    if isinstance(item, dict)
                ]
            else:
                roi_data = ui_state.get("roi")
                self.rois = (
                    [ImageROI.from_dict(roi_data)]
                    if roi_data else []
                )
            validated_rois = []
            for roi in self.rois:
                roi.validate(self.preview_image.shape)
                if self.loaded.domain == "bayer":
                    roi = roi.align_for_bayer(
                        self.preview_image.shape
                    )
                validated_rois.append(roi)
            self.rois = validated_rois
            self.active_roi_index = int(
                ui_state.get(
                    "active_roi_index",
                    0 if self.rois else -1,
                )
            )
            self.active_roi_index = (
                min(
                    max(self.active_roi_index, 0),
                    len(self.rois) - 1,
                )
                if self.rois else -1
            )
            self.roi = (
                self.rois[self.active_roi_index]
                if self.active_roi_index >= 0 else None
            )
            self.roi_process_var.set(bool(ui_state.get("process_roi", False) and self.roi))
            self.analysis_roi_var.set(bool(ui_state.get("analyze_roi", True)))
            self.channel_var.set(ui_state.get("channel", "RGB"))
            self.compare_var.set(bool(ui_state.get("compare", False)))
            self.compare_position = float(
                np.clip(ui_state.get("compare_position", 0.5), 0, 1)
            )
            self.clipping_var.set(bool(ui_state.get("clipping", False)))
            self.artifact_overlay_var.set(
                bool(ui_state.get("artifact_overlay", False))
            )
            self.expert_mode = bool(
                ui_state.get("expert_mode", False)
            )
            self.expert_mode_var.set(self.expert_mode)
            advanced_state = ui_state.get(
                "advanced_parameters", {}
            )
            if isinstance(advanced_state, dict):
                self.advanced_param_state = {
                    str(key): bool(value)
                    for key, value in advanced_state.items()
                }
            raw_scale = ui_state.get("ui_scale_mode", ui_state.get("ui_scale", "100%"))
            if isinstance(raw_scale, (int, float)):
                scale_value = float(raw_scale)
                scale_label = min(
                    UI_SCALE_CHOICES,
                    key=lambda label: abs(
                        UI_SCALE_CHOICES[label] - scale_value
                    ),
                )
            else:
                scale_label = str(raw_scale)
            if scale_label in UI_SCALE_CHOICES:
                self.ui_scale_var.set(scale_label)
                self.ui_scale = float(UI_SCALE_CHOICES[scale_label])
                configure_theme(self.root, self.ui_scale)
            waveform_mode = ui_state.get("waveform_mode", "RGB Overlay")
            if waveform_mode in {"Luma", "RGB Overlay", "RGB Parade"}:
                self.waveform_mode_var.set(waveform_mode)
            vectorscope_mode = ui_state.get("vectorscope_mode", "YCbCr")
            if vectorscope_mode in {"YCbCr", "CIE 1976 u'v'"}:
                self.vectorscope_mode_var.set(vectorscope_mode)
            self.vectorscope_scale_var.set(float(
                ui_state.get("vectorscope_scale", 1.0)
            ))
            self.pending_artifact = ui_state.get("artifact")
            self.selected_module_index = max(
                0,
                min(
                    int(ui_state.get("selected_module_index", 0)),
                    len(self.pipeline.modules) - 1,
                ),
            )
            self.fit_mode = bool(ui_state.get("fit_mode", True))
            self.zoom = float(np.clip(ui_state.get("zoom", 1.0), 0.05, 16.0))
            geometry = str(ui_state.get("window_geometry", ""))
            if re.fullmatch(r"\d+x\d+(?:[+-]\d+){2}", geometry):
                self.root.geometry(geometry)
            collapse = bool(ui_state.get("analysis_collapsed", False))
            if collapse != self.analysis_collapsed:
                self._toggle_analysis_panel()
            analysis_tab = str(
                ui_state.get(
                    "analysis_selected_tab",
                    ui_state.get("analysis_tab", "Histogram"),
                )
            )
            for tab_id in self.analysis_notebook.tabs():
                if self.analysis_notebook.tab(tab_id, "text") == analysis_tab:
                    self.analysis_notebook.select(tab_id)
                    break
            if bool(ui_state.get("performance_details_visible", False)):
                self.root.after_idle(self.show_performance_details)
            sashes = ui_state.get("main_sashes", [])
            if isinstance(sashes, list):
                self.root.after_idle(
                    lambda values=list(sashes): self._restore_main_sashes(
                        values
                    )
                )
            self._apply_expert_mode()
            warnings.extend(data.get("_warnings", []))
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc), parent=self.root)
            return
        self._refresh_pipeline_list()
        self._reset_manual_parameter_snapshots()
        self._store_current_work_item()
        stage_index = int(data.get("ui_state", {}).get("stage_index", self.stage_combo.current()))
        self._update_roi_label()
        self._on_module_select()
        self.stage_combo.current(max(0, min(stage_index, len(self.pipeline.modules))))
        self.schedule_process(immediate=True)
        if warnings:
            messagebox.showwarning(
                "配置已加载并调整",
                "\n".join(warnings[:12]),
                parent=self.root,
            )
        self.toast.show("ISP 配置已加载", "success")
        self.status_var.set(f"配置已加载：{path}")

    def export_main_output(self) -> None:
        previous = self.artifact_var.get()
        self.artifact_var.set("Main Output")
        try:
            self.export_current()
        finally:
            self.artifact_var.set(previous)

    def export_current(self) -> None:
        if not self.results:
            return
        result = self.results[self._current_result_index()]
        path = filedialog.asksaveasfilename(
            parent=self.root, title=f"导出 {result.name}",
            defaultextension=".png",
            filetypes=[("PNG 8-bit", "*.png"), ("TIFF 16-bit", "*.tif *.tiff")],
        )
        if not path:
            return
        try:
            artifact_name = self.artifact_var.get()
            if artifact_name != "Main Output" and artifact_name in result.artifacts:
                image = artifact_to_rgb(artifact_name, result.artifacts[artifact_name])
                domain = "rgb"
            else:
                image, domain = result.image, result.domain
            export_image(path, image, domain, self.loaded.metadata)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return
        self.toast.show(f"{result.name} 已导出", "success")
        self.status_var.set(f"已导出 {result.name}：{path}")

    def export_roi(self) -> None:
        if self.roi is None:
            self.toast.show("请先框选 ROI", "warning")
            return
        if not self.results:
            return
        result = self.results[self._current_result_index()]
        artifact_name = self.artifact_var.get()
        if artifact_name != "Main Output" and artifact_name in result.artifacts:
            source = artifact_to_rgb(artifact_name, result.artifacts[artifact_name])
            domain = "rgb"
        else:
            source = result.image
            domain = result.domain
        if not self.roi_process_var.get() and source.shape[:2] == self.preview_image.shape[:2]:
            ys, xs = self.roi.slices()
            source = source[ys, xs]
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title=f"导出 ROI · {result.name}",
            defaultextension=".png",
            filetypes=[("PNG 8-bit", "*.png"), ("TIFF 16-bit", "*.tif *.tiff")],
        )
        if not path:
            return
        try:
            export_image(path, source, domain, self.loaded.metadata)
        except Exception as exc:
            messagebox.showerror("导出 ROI 失败", str(exc), parent=self.root)
            return
        self.toast.show("ROI 已导出", "success")
        self.status_var.set(f"ROI 已导出：{path}")

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于",
            "ISP RAW Visual Simulator 0.4.4\n\n"
            "用于 RAW ISP 模块的离线视觉效果快速仿真。\n"
            "内部使用 float32；当前不保证与硬件 ISP 逐位一致。",
            parent=self.root,
        )

    def close(self) -> None:
        self.generation += 1
        self.analysis_generation += 1
        self.import_generation += 1
        if self.pending_after:
            try:
                self.root.after_cancel(self.pending_after)
            except tk.TclError:
                pass
            self.pending_after = None
        for attr in (
            "analysis_pending_after",
            "canvas_resize_after",
            "canvas_overlay_after",
            "view_render_after",
            "import_poll_after",
        ):
            after_id = getattr(self, attr, None)
            if after_id:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        for after_id in tuple(self.poll_after_ids):
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self.poll_after_ids.clear()
        for after_id in tuple(self.analysis_poll_after_ids):
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self.analysis_poll_after_ids.clear()
        if (
            self.calibration_workspace is not None
            and self.calibration_workspace.winfo_exists()
        ):
            self.calibration_workspace.close()
        self.toast.close()
        self.wheel_router.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.analysis_executor.shutdown(wait=False, cancel_futures=True)
        self.io_executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main() -> None:
    enable_process_dpi_awareness()
    root = tk.Tk()
    ISPApplication(root)
    root.mainloop()
