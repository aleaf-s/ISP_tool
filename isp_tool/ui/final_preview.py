from __future__ import annotations

import copy
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import ttk
from typing import Dict, Optional

import numpy as np
from PIL import Image, ImageTk

from ..pipeline import ISPPipeline
from ..preview import display_rgb
from .theme import COLORS, FONTS


def compute_impact_metrics(
    final_rgb: np.ndarray, bypass_rgb: np.ndarray
) -> Dict[str, float]:
    """Measure the visible final-output change caused by one module."""

    final = np.asarray(final_rgb, dtype=np.float32)
    bypass = np.asarray(bypass_rgb, dtype=np.float32)
    if final.shape != bypass.shape:
        raise ValueError("Impact comparison images must have equal shape")
    difference = np.abs(final - bypass)
    pixel_difference = np.mean(difference, axis=2)
    return {
        "mean_abs": float(np.mean(difference)),
        "p95_abs": float(np.percentile(difference, 95.0)),
        "max_abs": float(np.max(difference, initial=0.0)),
        "changed_ratio": float(
            np.mean(pixel_difference > (1.0 / 255.0))
        ),
    }


def impact_heatmap(
    final_rgb: np.ndarray, bypass_rgb: np.ndarray
) -> np.ndarray:
    difference = np.mean(
        np.abs(
            np.asarray(final_rgb, np.float32)
            - np.asarray(bypass_rgb, np.float32)
        ),
        axis=2,
    )
    scale = float(np.percentile(difference, 99.0))
    normalized = np.clip(
        difference / max(scale, 1e-6), 0.0, 1.0
    )
    return np.stack(
        (
            normalized,
            np.sqrt(normalized) * 0.55,
            np.maximum(normalized - 0.65, 0.0) * 0.35,
        ),
        axis=2,
    ).astype(np.float32)


class _PreviewPane(ttk.Frame):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title_var = tk.StringVar(value=title)
        ttk.Label(
            self, textvariable=self.title_var,
            style="Title.TLabel",
        ).pack(anchor="w", padx=8, pady=(7, 4))
        self.canvas = tk.Canvas(
            self,
            bg=COLORS["canvas"],
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.array: Optional[np.ndarray] = None
        self.photo: Optional[ImageTk.PhotoImage] = None
        self.canvas.bind(
            "<Configure>", lambda _event: self._render()
        )

    def set_image(self, array: np.ndarray, title: str = "") -> None:
        self.array = np.asarray(array, np.float32)
        if title:
            self.title_var.set(title)
        self._render()

    def clear(self, message: str = "Waiting") -> None:
        self.array = None
        self.photo = None
        self.canvas.delete("all")
        self.canvas.create_text(
            max(self.canvas.winfo_width(), 100) // 2,
            max(self.canvas.winfo_height(), 80) // 2,
            text=message,
            fill=COLORS["muted"],
            font=FONTS["body"],
        )

    def _render(self) -> None:
        if self.array is None:
            return
        height = max(self.canvas.winfo_height(), 100)
        width = max(self.canvas.winfo_width(), 120)
        source = np.round(
            np.clip(self.array, 0.0, 1.0) * 255.0
        ).astype(np.uint8)
        image = Image.fromarray(source)
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(
            width // 2,
            height // 2,
            image=self.photo,
            anchor="center",
        )


class FinalImpactWindow(tk.Toplevel):
    """Compare final output with the final output after bypassing one module."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title(self.app.tr("final.title"))
        self.geometry("1260x760")
        self.minsize(940, 620)
        self.transient(parent)
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="isp-final-impact"
        )
        self.future: Optional[Future] = None
        self.poll_after: Optional[str] = None
        self.generation = 0
        self.cache: Dict[str, Dict[str, object]] = {}
        self.baseline_stage = None
        self.source = None
        self.domain = ""
        self.metadata = None
        self.snapshot = []
        self.module_ids = []
        self.status_var = tk.StringVar(value="Ready")
        self.metrics_var = tk.StringVar(
            value="选择一个模块，查看它对最终输出的影响。"
        )
        self._build()
        self.refresh_language()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_from_app()

    def refresh_language(self) -> None:
        self.title(self.app.tr("final.title"))
        self.refresh_button.configure(text=self.app.tr("final.refresh"))
        self.select_label.configure(text=self.app.tr("final.select"))
        self.explanation_label.configure(
            text=self.app.tr("final.explanation")
        )
        self.notebook.tab(0, text=self.app.tr("final.compare"))
        self.notebook.tab(1, text=self.app.tr("final.heatmap"))

    def _build(self) -> None:
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill="x")
        ttk.Label(
            toolbar,
            text="FINAL OUTPUT IMPACT",
            style="Title.TLabel",
        ).pack(side="left")
        self.refresh_button = ttk.Button(
            toolbar,
            text="刷新当前图像和参数",
            command=self.refresh_from_app,
        )
        self.refresh_button.pack(side="right")
        ttk.Label(
            toolbar, textvariable=self.status_var,
            style="Muted.TLabel",
        ).pack(side="right", padx=12)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10)
        left = ttk.Frame(body, width=245, padding=(0, 6, 8, 6))
        center = ttk.Frame(body)
        body.add(left, weight=0)
        body.add(center, weight=1)

        self.select_label = ttk.Label(
            left, text="选择临时旁路模块",
            style="Title.TLabel",
        )
        self.select_label.pack(anchor="w", pady=(0, 6))
        self.module_list = tk.Listbox(
            left,
            bg=COLORS["panel_alt"],
            fg=COLORS["foreground"],
            selectbackground=COLORS["selection"],
            selectforeground="white",
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            activestyle="none",
            font=FONTS["body"],
        )
        self.module_list.pack(fill="both", expand=True)
        self.module_list.bind(
            "<<ListboxSelect>>", self._module_selected
        )
        self.explanation_label = ttk.Label(
            left,
            text=(
                "这里采用临时旁路（ablation）比较。结果表示该模块"
                "在当前整条流水线中的净影响，非独立线性贡献。"
            ),
            style="Muted.TLabel",
            wraplength=220,
        )
        self.explanation_label.pack(fill="x", pady=(8, 0))

        self.notebook = ttk.Notebook(center)
        self.notebook.pack(fill="both", expand=True)
        compare_tab = ttk.Frame(self.notebook)
        difference_tab = ttk.Frame(self.notebook)
        self.notebook.add(compare_tab, text="最终效果对比")
        self.notebook.add(difference_tab, text="影响热力图")
        compare = ttk.Panedwindow(
            compare_tab, orient="horizontal"
        )
        compare.pack(fill="both", expand=True)
        self.final_pane = _PreviewPane(compare, "FINAL · 全部启用")
        self.bypass_pane = _PreviewPane(compare, "BYPASS")
        compare.add(self.final_pane, weight=1)
        compare.add(self.bypass_pane, weight=1)
        self.diff_pane = _PreviewPane(
            difference_tab, "DIFFERENCE · P99 归一化"
        )
        self.diff_pane.pack(fill="both", expand=True)

        footer = ttk.Frame(self, padding=(10, 7))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            textvariable=self.metrics_var,
            style="Muted.TLabel",
        ).pack(anchor="w")

    def refresh_from_app(self) -> None:
        self.generation += 1
        if self.future is not None and not self.future.done():
            self.future.cancel()
        self.cache.clear()
        self.baseline_stage = None
        self.source = np.asarray(
            self.app.preview_image, np.float32
        ).copy()
        self.domain = self.app.loaded.domain
        self.metadata = copy.deepcopy(self.app.loaded.metadata)
        self.snapshot = copy.deepcopy(self.app.pipeline.snapshot())
        try:
            cache_matches = (
                self.app.pipeline_cache.get("input_revision")
                == self.app.input_revision
                and self.app.pipeline_cache.get(
                    "backend_cache_key"
                ) == self.app.pipeline.backend_cache_key
                and self.app.pipeline_cache.get("snapshot")
                == self.snapshot
                and self.app.pipeline_cache.get(
                    "last_metrics", {}
                ).get("roi") is None
            )
        except (TypeError, ValueError):
            cache_matches = False
        if (
            self.app.results
            and not self.app.roi_process_var.get()
            and cache_matches
            and self.app.results[-1].image.shape[:2]
            == self.source.shape[:2]
        ):
            self.baseline_stage = copy.deepcopy(
                self.app.results[-1]
            )
        self.module_ids = [
            str(item.get("id")) for item in self.snapshot
        ]
        self.module_list.delete(0, "end")
        for index, (module, config) in enumerate(
            zip(self.app.pipeline.modules, self.snapshot), start=1
        ):
            state = "●" if config.get("enabled", True) else "○"
            self.module_list.insert(
                "end", f"{index:02d}  {state}  {module.name}"
            )
        if self.baseline_stage is not None:
            self.final_pane.set_image(
                display_rgb(
                    self.baseline_stage.image,
                    self.baseline_stage.domain,
                    self.metadata,
                    data_state=self.baseline_stage.data_state,
                ),
                "FINAL · 全部启用",
            )
        else:
            self.final_pane.clear("正在准备最终输出")
        self.bypass_pane.clear("请选择模块")
        self.diff_pane.clear("请选择模块")
        self.metrics_var.set(
            "选择一个模块，查看旁路后最终输出发生了什么变化。"
        )
        self.status_var.set(
            f"{self.app.current_image_index + 1}/"
            f"{len(self.app.work_items)} · "
            f"{self.app.work_items[self.app.current_image_index].label}"
        )
        if self.module_ids:
            self.module_list.selection_set(0)
            self._module_selected()

    def _module_selected(self, _event=None) -> None:
        selection = self.module_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        module_id = self.module_ids[index]
        module_name = self.app.pipeline.modules[index].name
        cached = self.cache.get(module_id)
        if cached is not None:
            self._apply_payload(cached)
            return
        self.generation += 1
        generation = self.generation
        if self.future is not None and not self.future.done():
            self.future.cancel()
        source = self.source.copy()
        domain = self.domain
        metadata = copy.deepcopy(self.metadata)
        snapshot = copy.deepcopy(self.snapshot)
        baseline_stage = self.baseline_stage
        backend = self.app.pipeline.backend
        backend_preference = self.app.pipeline.backend_preference
        self.status_var.set(f"正在计算：{module_name}")
        self.bypass_pane.clear(f"正在旁路 {module_name}")
        self.diff_pane.clear("正在计算影响")

        def task():
            pipeline = ISPPipeline(
                backend=backend,
                backend_preference=backend_preference,
            )
            baseline = baseline_stage
            if baseline is None:
                baseline = pipeline.process(
                    source, domain, metadata,
                    snapshot=snapshot,
                )[-1]
            bypass_snapshot = copy.deepcopy(snapshot)
            bypass_snapshot[index]["enabled"] = False
            bypass = pipeline.process(
                source, domain, metadata,
                snapshot=bypass_snapshot,
            )[-1]
            final_rgb = display_rgb(
                baseline.image, baseline.domain, metadata,
                data_state=baseline.data_state,
            )
            bypass_rgb = display_rgb(
                bypass.image, bypass.domain, metadata,
                data_state=bypass.data_state,
            )
            return {
                "module_id": module_id,
                "module_name": module_name,
                "baseline_stage": baseline,
                "final_rgb": final_rgb,
                "bypass_rgb": bypass_rgb,
                "heatmap": impact_heatmap(
                    final_rgb, bypass_rgb
                ),
                "metrics": compute_impact_metrics(
                    final_rgb, bypass_rgb
                ),
                "already_disabled": not bool(
                    snapshot[index].get("enabled", True)
                ),
            }

        self.future = self.executor.submit(task)
        self._poll(self.future, generation)

    def _poll(self, future: Future, generation: int) -> None:
        if generation != self.generation or not self.winfo_exists():
            return
        if not future.done():
            self.poll_after = self.after(
                35, lambda: self._poll(future, generation)
            )
            return
        self.poll_after = None
        try:
            payload = future.result()
        except Exception as exc:
            self.status_var.set("计算失败")
            self.metrics_var.set(str(exc))
            return
        if generation != self.generation:
            return
        self.baseline_stage = payload["baseline_stage"]
        self.cache[str(payload["module_id"])] = payload
        self._apply_payload(payload)

    def _apply_payload(self, payload) -> None:
        name = str(payload["module_name"])
        self.final_pane.set_image(
            payload["final_rgb"], "FINAL · 全部启用"
        )
        self.bypass_pane.set_image(
            payload["bypass_rgb"], f"BYPASS · {name}"
        )
        self.diff_pane.set_image(
            payload["heatmap"],
            f"DIFFERENCE · {name} · P99 归一化",
        )
        metrics = payload["metrics"]
        suffix = (
            " · 当前模块原本已禁用"
            if payload.get("already_disabled") else ""
        )
        self.metrics_var.set(
            f"{name} · Mean |Δ| {metrics['mean_abs']:.6f} · "
            f"P95 {metrics['p95_abs']:.6f} · "
            f"Max {metrics['max_abs']:.6f} · "
            f"Changed {metrics['changed_ratio'] * 100:.2f}%"
            f"{suffix}"
        )
        height, width = payload["final_rgb"].shape[:2]
        self.status_var.set(
            f"Ready · {width}×{height} preview"
        )

    def close(self) -> None:
        self.generation += 1
        if self.poll_after is not None:
            try:
                self.after_cancel(self.poll_after)
            except tk.TclError:
                pass
            self.poll_after = None
        if self.future is not None and not self.future.done():
            self.future.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.app.final_preview_window = None
        self.destroy()
