from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable, List, Optional

from ...models import ImageROI
from ..theme import COLORS


@dataclass
class ROIItem:
    roi: ImageROI
    mean: Optional[float] = None
    variance: Optional[float] = None
    gradient: Optional[float] = None
    accepted: Optional[bool] = None
    reason: str = ""

    @property
    def status(self) -> str:
        if self.accepted is None:
            return "Pending"
        if self.accepted:
            return "Accepted"
        return f"Rejected: {self.reason}"

    @property
    def status_tag(self) -> str:
        if self.accepted is None:
            return ""
        return "accepted" if self.accepted else "rejected"


class ROIList(ttk.Frame):
    def __init__(
        self,
        parent,
        on_select: Optional[Callable[[ROIItem], None]] = None,
    ):
        super().__init__(parent)
        self.on_select = on_select
        self.tree = ttk.Treeview(
            self,
            columns=("id", "roi", "mean", "variance", "gradient", "status"),
            show="headings",
            style="Status.Treeview",
            height=3,
        )
        for key, label, width in (
            ("id", "#", 28),
            ("roi", "ROI", 125),
            ("mean", "Mean", 55),
            ("variance", "Variance", 62),
            ("gradient", "Gradient", 62),
            ("status", "Status", 100),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        self.tree.tag_configure("accepted", foreground=COLORS["success"])
        self.tree.tag_configure("rejected", foreground=COLORS["warning"])
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self._items: List[ROIItem] = []
        self._remove_action: Optional[Callable[[], None]] = None
        self._clear_action: Optional[Callable[[], None]] = None
        self._analyze_action: Optional[Callable[[], None]] = None
        self._context = tk.Menu(self, tearoff=False)
        self._context.add_command(
            label="Analyze selected", command=self._invoke_analyze
        )
        self._context.add_command(
            label="Remove selected", command=self._invoke_remove
        )
        self._context.add_command(label="Clear list", command=self._invoke_clear)
        self.tree.bind("<Button-3>", self._show_context)
        self.tree.bind("<Delete>", lambda _event: self._invoke_remove())
        self.tree.bind("<Return>", lambda _event: self._invoke_analyze())

    def configure_actions(
        self,
        remove: Optional[Callable[[], None]] = None,
        clear: Optional[Callable[[], None]] = None,
        analyze: Optional[Callable[[], None]] = None,
    ) -> None:
        self._remove_action = remove
        self._clear_action = clear
        self._analyze_action = analyze

    def _show_context(self, event) -> str:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
        has_selection = bool(self.tree.selection())
        self._context.entryconfigure(
            0, state="normal" if has_selection else "disabled"
        )
        self._context.entryconfigure(
            1, state="normal" if has_selection else "disabled"
        )
        self._context.entryconfigure(
            2, state="normal" if self._items else "disabled"
        )
        self._context.tk_popup(event.x_root, event.y_root)
        return "break"

    def _invoke_remove(self) -> None:
        if self._remove_action is not None:
            self._remove_action()
        else:
            self.remove_selected()

    def _invoke_clear(self) -> None:
        if self._clear_action is not None:
            self._clear_action()
        else:
            self.clear()

    def _invoke_analyze(self) -> None:
        if self._analyze_action is not None:
            self._analyze_action()

    def set_items(self, items: Iterable[ROIItem]) -> None:
        self._items = list(items)
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self._items):
            status = item.status
            tag = item.status_tag
            roi = item.roi
            self.tree.insert(
                "", "end", iid=str(index),
                values=(
                    index + 1,
                    f"{roi.x},{roi.y} {roi.width}×{roi.height}",
                    self._number(item.mean),
                    self._number(item.variance),
                    self._number(item.gradient),
                    status,
                ),
                tags=(tag,) if tag else (),
            )

    def items(self) -> List[ROIItem]:
        return list(self._items)

    def add(self, item: ROIItem) -> None:
        self.set_items([*self._items, item])

    def remove_selected(self) -> Optional[ROIItem]:
        selected = self.tree.selection()
        if not selected:
            return None
        item = self._items.pop(int(selected[0]))
        self.set_items(self._items)
        return item

    def clear(self) -> None:
        self.set_items([])

    def _selected(self, _event=None) -> None:
        selected = self.tree.selection()
        if selected and self.on_select:
            self.on_select(self._items[int(selected[0])])

    @staticmethod
    def _number(value: Optional[float]) -> str:
        return "—" if value is None else f"{value:.4g}"
