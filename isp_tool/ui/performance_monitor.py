from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from .performance_metrics import PerformanceMetrics, format_bytes
from .theme import COLORS


class PerformanceMonitorWindow(tk.Toplevel):
    """Non-modal structured view over the shared performance collector."""

    def __init__(
        self,
        master: tk.Misc,
        metrics: PerformanceMetrics,
        translator: Callable[[str], str],
        *,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
        self.metrics = metrics
        self.tr = translator
        self.on_close_callback = on_close
        self._refresh_after = None
        self.title(self.tr("performance.title"))
        self.geometry("900x620")
        self.minsize(720, 480)
        self.configure(bg=COLORS["background"])
        self.protocol("WM_DELETE_WINDOW", self.close)

        header = ttk.Frame(self, style="Panel.TFrame")
        header.pack(fill="x", padx=12, pady=(12, 6))
        self.summary_var = tk.StringVar()
        ttk.Label(
            header,
            textvariable=self.summary_var,
            style="Title.TLabel",
        ).pack(anchor="w")
        self.note_var = tk.StringVar()
        ttk.Label(
            header,
            textvariable=self.note_var,
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.timing_tab = ttk.Frame(notebook)
        self.resources_tab = ttk.Frame(notebook)
        self.tasks_tab = ttk.Frame(notebook)
        notebook.add(self.timing_tab, text=self.tr("performance.timing"))
        notebook.add(
            self.resources_tab, text=self.tr("performance.resources")
        )
        notebook.add(self.tasks_tab, text=self.tr("performance.tasks"))
        self.notebook = notebook

        self.timing_tree = self._tree(
            self.timing_tab,
            ("latest", "average", "p95", "maximum", "count"),
            ("Latest", "Average", "P95", "Max", "Samples"),
            (105, 105, 105, 105, 80),
        )

        resource_pane = ttk.Panedwindow(
            self.resources_tab, orient="vertical"
        )
        resource_pane.pack(fill="both", expand=True)
        cache_frame = ttk.Labelframe(
            resource_pane,
            text=self.tr("performance.software_caches"),
            style="Section.TLabelframe",
        )
        memory_frame = ttk.Labelframe(
            resource_pane,
            text=self.tr("performance.memory_estimate"),
            style="Section.TLabelframe",
        )
        resource_pane.add(cache_frame, weight=1)
        resource_pane.add(memory_frame, weight=1)
        self.cache_frame = cache_frame
        self.memory_frame = memory_frame
        self.cache_tree = self._tree(
            cache_frame,
            ("hits", "misses", "requests", "rate"),
            ("Hits", "Misses", "Requests", "Hit Rate"),
            (105, 105, 105, 115),
        )
        self.memory_tree = self._tree(
            memory_frame,
            ("bytes",),
            ("Estimated Size",),
            (180,),
        )

        task_pane = ttk.Panedwindow(self.tasks_tab, orient="vertical")
        task_pane.pack(fill="both", expand=True)
        counter_frame = ttk.Labelframe(
            task_pane,
            text=self.tr("performance.task_counters"),
            style="Section.TLabelframe",
        )
        state_frame = ttk.Labelframe(
            task_pane,
            text=self.tr("performance.runtime_state"),
            style="Section.TLabelframe",
        )
        task_pane.add(counter_frame, weight=1)
        task_pane.add(state_frame, weight=1)
        self.counter_frame = counter_frame
        self.state_frame = state_frame
        self.counter_tree = self._tree(
            counter_frame, ("value",), ("Count",), (140,)
        )
        self.state_tree = self._tree(
            state_frame, ("value",), ("Value",), (320,)
        )

        self.refresh()

    @staticmethod
    def _tree(
        parent: tk.Misc,
        columns: tuple[str, ...],
        labels: tuple[str, ...],
        widths: tuple[int, ...],
    ) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        tree = ttk.Treeview(
            frame,
            columns=columns,
            show="tree headings",
            style="Status.Treeview",
        )
        tree.heading("#0", text="Metric")
        tree.column("#0", width=260, minwidth=160, stretch=True)
        for name, label, width in zip(columns, labels, widths):
            tree.heading(name, text=label)
            tree.column(name, width=width, minwidth=70, anchor="e")
        scrollbar = ttk.Scrollbar(
            frame, orient="vertical", command=tree.yview
        )
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return tree

    @staticmethod
    def _replace_rows(tree: ttk.Treeview, rows: list[tuple]) -> None:
        for item in tree.get_children(""):
            tree.delete(item)
        for name, values in rows:
            tree.insert("", "end", text=name, values=values)

    def refresh_language(self) -> None:
        self.title(self.tr("performance.title"))
        self.notebook.tab(0, text=self.tr("performance.timing"))
        self.notebook.tab(1, text=self.tr("performance.resources"))
        self.notebook.tab(2, text=self.tr("performance.tasks"))
        self.cache_frame.configure(
            text=self.tr("performance.software_caches")
        )
        self.memory_frame.configure(
            text=self.tr("performance.memory_estimate")
        )
        self.counter_frame.configure(
            text=self.tr("performance.task_counters")
        )
        self.state_frame.configure(
            text=self.tr("performance.runtime_state")
        )
        self.refresh()

    def refresh(self) -> None:
        if not self.winfo_exists():
            return
        if self._refresh_after is not None:
            try:
                self.after_cancel(self._refresh_after)
            except tk.TclError:
                pass
            self._refresh_after = None
        snapshot = self.metrics.structured_snapshot()
        self.summary_var.set(self.metrics.status_text())
        self.note_var.set(self.tr("performance.memory_note"))

        timing_rows = []
        for name, timing in sorted(
            snapshot.timings.items(),
            key=lambda item: item[1].average,
            reverse=True,
        ):
            display_name = name.removeprefix("module:")
            timing_rows.append(
                (
                    display_name,
                    (
                        f"{timing.latest:.2f} ms",
                        f"{timing.average:.2f} ms",
                        f"{timing.p95:.2f} ms",
                        f"{timing.maximum:.2f} ms",
                        timing.count,
                    ),
                )
            )
        self._replace_rows(self.timing_tree, timing_rows)

        cache_rows = [
            (
                name,
                (
                    cache.hits,
                    cache.misses,
                    cache.requests,
                    f"{cache.hit_rate * 100:.1f}%"
                    if cache.requests else "--",
                ),
            )
            for name, cache in sorted(snapshot.caches.items())
        ]
        self._replace_rows(self.cache_tree, cache_rows)
        self._replace_rows(
            self.memory_tree,
            [
                (name, (f"~{format_bytes(value)}",))
                for name, value in sorted(snapshot.memory_bytes.items())
            ],
        )
        self._replace_rows(
            self.counter_tree,
            [
                (name, (value,))
                for name, value in sorted(snapshot.counters.items())
            ],
        )
        self._replace_rows(
            self.state_tree,
            [
                (name, (value,))
                for name, value in sorted(snapshot.values.items())
            ],
        )
        self._refresh_after = self.after(500, self.refresh)

    def close(self) -> None:
        if self._refresh_after is not None:
            try:
                self.after_cancel(self._refresh_after)
            except tk.TclError:
                pass
            self._refresh_after = None
        callback = self.on_close_callback
        self.on_close_callback = None
        if callback is not None:
            callback()
        self.destroy()
