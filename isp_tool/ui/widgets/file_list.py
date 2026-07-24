from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable, List, Optional

from ...models import RawMetadata
from ..theme import COLORS


@dataclass
class CalibrationFileItem:
    path: str
    width: int
    height: int
    bit_depth: int
    bayer_pattern: str
    loaded: bool = True
    validation: str = "Valid"
    message: str = ""

    @property
    def filename(self) -> str:
        return Path(self.path).name


def validate_file_metadata(
    item: CalibrationFileItem, reference: RawMetadata
) -> str:
    issues = []
    if item.width != reference.width or item.height != reference.height:
        issues.append("Size")
    if item.bit_depth != reference.bit_depth:
        issues.append("Bit depth")
    if item.bayer_pattern != reference.bayer_pattern:
        issues.append("Bayer")
    return "Valid" if not issues else "Mismatch: " + ", ".join(issues)


class FileList(ttk.Frame):
    def __init__(self, parent, title: str = "Files"):
        super().__init__(parent)
        ttk.Label(self, text=title, style="Title.TLabel").pack(anchor="w")
        self.tree = ttk.Treeview(
            self,
            columns=("file", "size", "bit", "bayer", "loaded", "validation"),
            show="headings",
            style="Status.Treeview",
            height=3,
        )
        for key, label, width in (
            ("file", "File", 145),
            ("size", "Size", 80),
            ("bit", "Bit", 38),
            ("bayer", "Bayer", 55),
            ("loaded", "Loaded", 52),
            ("validation", "Validation", 95),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        self.tree.tag_configure("invalid", foreground=COLORS["error"])
        self.tree.pack(fill="both", expand=True, pady=(3, 0))
        self._items: List[CalibrationFileItem] = []
        self._remove_action: Optional[Callable[[], None]] = None
        self._clear_action: Optional[Callable[[], None]] = None
        self._validate_action: Optional[Callable[[], None]] = None
        self._context = tk.Menu(self, tearoff=False)
        self._context.add_command(
            label="Remove selected", command=self._invoke_remove
        )
        self._context.add_command(label="Clear list", command=self._invoke_clear)
        self._context.add_separator()
        self._context.add_command(label="Validate", command=self._invoke_validate)
        self.tree.bind("<Button-3>", self._show_context)
        self.tree.bind("<Delete>", lambda _event: self._invoke_remove())
        self.tree.bind("<Return>", lambda _event: self._invoke_validate())

    def configure_actions(
        self,
        remove: Optional[Callable[[], None]] = None,
        clear: Optional[Callable[[], None]] = None,
        validate: Optional[Callable[[], None]] = None,
    ) -> None:
        self._remove_action = remove
        self._clear_action = clear
        self._validate_action = validate

    def _show_context(self, event) -> str:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
        has_selection = bool(self.tree.selection())
        self._context.entryconfigure(
            0, state="normal" if has_selection else "disabled"
        )
        self._context.entryconfigure(
            1, state="normal" if self._items else "disabled"
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

    def _invoke_validate(self) -> None:
        if self._validate_action is not None:
            self._validate_action()

    def set_items(self, items: Iterable[CalibrationFileItem]) -> None:
        self._items = list(items)
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self._items):
            valid = item.validation == "Valid"
            self.tree.insert(
                "", "end", iid=str(index),
                values=(
                    item.filename,
                    f"{item.width}×{item.height}",
                    item.bit_depth,
                    item.bayer_pattern,
                    "Yes" if item.loaded else "No",
                    item.validation,
                ),
                tags=() if valid else ("invalid",),
            )

    def items(self) -> List[CalibrationFileItem]:
        return list(self._items)

    def remove_selected(self) -> Optional[CalibrationFileItem]:
        selected = self.tree.selection()
        if not selected:
            return None
        index = int(selected[0])
        item = self._items.pop(index)
        self.set_items(self._items)
        return item

    def clear(self) -> None:
        self.set_items([])
