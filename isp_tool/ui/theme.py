from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk


COLORS = {
    "background": "#11151B",
    "panel": "#181E27",
    "panel_alt": "#202834",
    "canvas": "#080B0F",
    "canvas_alt": "#0B0F14",
    "foreground": "#E5E9EF",
    "muted": "#98A4B3",
    "border": "#303A48",
    "accent": "#35A7FF",
    "accent_dark": "#147DBE",
    "selection": "#176DA2",
    "success": "#40C88A",
    "warning": "#F2B84B",
    "warning_panel": "#21171A",
    "warning_text": "#FF9AA9",
    "error": "#FF5C72",
    "preview": "#62B8FF",
    "candidate": "#FFD84D",
    "calibration_overlay": "#54F0C0",
    "underexposure": "#27D7E7",
    "overexposure": "#F04DFF",
    "grid": "#27313D",
    "guide": "#596574",
    "scope_grid": "#39424F",
    "channel_r": "#FF5368",
    "channel_g": "#42D68A",
    "channel_b": "#4C93FF",
    "channel_y": "#D9DDE4",
}

FONT_NAMES = {
    "body": "ISPBodyFont",
    "body_large": "ISPBodyLargeFont",
    "title": "ISPTitleFont",
    "section": "ISPSectionFont",
    "small": "ISPSmallFont",
    "mono": "ISPMonoFont",
}
FONTS = FONT_NAMES

UI_SCALE_CHOICES = {
    "Follow System": 1.0,
    "90%": 0.9,
    "100%": 1.0,
    "110%": 1.1,
    "125%": 1.25,
    "150%": 1.5,
}

PADDING = {
    "xs": 3,
    "sm": 6,
    "md": 10,
    "lg": 14,
}

CONTROL_HEIGHT = 28

STATUS_COLORS = {
    "NOT_ANALYZED": COLORS["muted"],
    "RUNNING": COLORS["accent"],
    "SUGGESTED": COLORS["accent"],
    "PREVIEWING": COLORS["preview"],
    "APPLIED": COLORS["success"],
    "STALE": COLORS["warning"],
    "FAILED": COLORS["error"],
    "CANCELLED": COLORS["muted"],
    "WARNING": COLORS["warning"],
}

ARTIFACT_RGB = {
    "hot": (1.0, 0.1, 0.05),
    "dead": (0.05, 0.35, 1.0),
    "candidate": (1.0, 0.82, 0.1),
    "accepted": (0.15, 0.82, 0.45),
    "rejected": (1.0, 0.48, 0.08),
    "overexposure": (0.94, 0.18, 1.0),
    "underexposure": (0.08, 0.85, 0.9),
}


def _font(
    root: tk.Misc,
    name: str,
    family: str,
    size: int,
    weight: str = "normal",
) -> tkfont.Font:
    names = set(root.tk.call("font", "names"))
    value = tkfont.Font(
        root=root, name=name, exists=name in names
    )
    value.configure(
        family=family, size=max(8, int(size)), weight=weight
    )
    return value


def configure_named_fonts(
    root: tk.Misc, ui_scale: float = 1.0
) -> dict:
    scale = min(1.5, max(0.9, float(ui_scale)))
    specs = {
        "body": ("Segoe UI", 10, "normal"),
        "body_large": ("Segoe UI", 11, "normal"),
        "title": ("Segoe UI", 12, "bold"),
        "section": ("Segoe UI", 10, "bold"),
        "small": ("Segoe UI", 9, "normal"),
        "mono": ("Consolas", 10, "normal"),
    }
    previous = getattr(root, "_isp_named_fonts", {})
    output = {}
    for key, (family, size, weight) in specs.items():
        value = previous.get(key) if isinstance(previous, dict) else None
        if value is None:
            value = _font(
                root,
                FONT_NAMES[key],
                family,
                round(size * scale),
                weight,
            )
        else:
            value.configure(
                family=family,
                size=max(8, round(size * scale)),
                weight=weight,
            )
        output[key] = value
    # A newly-created named Font is deleted when its Python wrapper is
    # garbage-collected. Keep the wrappers with the owning Tk interpreter.
    setattr(root, "_isp_named_fonts", output)
    for standard in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.Font(
                root=root, name=standard, exists=True
            ).configure(
                family="Segoe UI", size=round(10 * scale)
            )
        except tk.TclError:
            pass
    try:
        tkfont.Font(
            root=root, name="TkHeadingFont", exists=True
        ).configure(
            family="Segoe UI", size=round(10 * scale), weight="bold"
        )
        tkfont.Font(
            root=root, name="TkFixedFont", exists=True
        ).configure(
            family="Consolas", size=round(10 * scale)
        )
    except tk.TclError:
        pass
    return output


def configure_theme(
    root: tk.Misc, ui_scale: float = 1.0
) -> ttk.Style:
    scale = min(1.5, max(0.9, float(ui_scale)))
    configure_named_fonts(root, scale)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    c = COLORS
    style.configure(
        ".", background=c["panel"], foreground=c["foreground"],
        fieldbackground=c["panel_alt"], font=FONTS["body"],
    )
    style.configure("App.TFrame", background=c["background"])
    style.configure("Panel.TFrame", background=c["panel"])
    style.configure("Inspector.TFrame", background=c["panel"])
    style.configure("Dark.TFrame", background=c["background"])
    style.configure("TFrame", background=c["panel"])
    style.configure("TLabel", background=c["panel"], foreground=c["foreground"])
    style.configure("Title.TLabel", font=FONTS["title"], foreground=c["foreground"])
    style.configure("Muted.TLabel", foreground=c["muted"])
    style.configure("Success.TLabel", foreground=c["success"])
    style.configure("Warning.TLabel", foreground=c["warning"])
    style.configure("Error.TLabel", foreground=c["error"])
    style.configure("Preview.TLabel", foreground=c["preview"])
    style.configure(
        "Section.TLabelframe", background=c["panel"],
        bordercolor=c["border"], relief="solid", borderwidth=1,
    )
    style.configure(
        "Section.TLabelframe.Label", background=c["panel"],
        foreground=c["foreground"], font=FONTS["section"],
    )
    style.configure(
        "TButton", background=c["panel_alt"], foreground=c["foreground"],
        padding=(round(9 * scale), round(6 * scale)),
        bordercolor=c["border"],
    )
    style.map("TButton", background=[("active", "#2C3745"), ("disabled", c["panel"])])
    style.configure(
        "Primary.TButton", background=c["accent_dark"], foreground="white",
    )
    style.map("Primary.TButton", background=[("active", c["accent"])])
    style.configure(
        "Secondary.TButton", background=c["panel_alt"], foreground=c["foreground"],
    )
    style.configure("Danger.TButton", background="#7D2940", foreground="white")
    style.map("Danger.TButton", background=[("active", c["error"])])
    style.configure("Accent.TButton", background=c["accent_dark"], foreground="white")
    style.map("Accent.TButton", background=[("active", c["accent"])])
    style.configure("TCheckbutton", background=c["panel"], foreground=c["foreground"])
    style.map("TCheckbutton", background=[("active", c["panel"])])
    style.configure(
        "TEntry", fieldbackground=c["panel_alt"], foreground=c["foreground"],
        insertcolor=c["foreground"],
    )
    style.configure("TCombobox", fieldbackground=c["panel_alt"], foreground=c["foreground"])
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", c["panel_alt"])],
        foreground=[("readonly", c["foreground"])],
    )
    style.configure("Horizontal.TScale", background=c["panel"], troughcolor=c["border"])
    style.configure("TNotebook", background=c["background"], borderwidth=0)
    style.configure(
        "TNotebook.Tab", background=c["panel_alt"], foreground=c["muted"],
        padding=(round(10 * scale), round(6 * scale)),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", c["panel"])],
        foreground=[("selected", c["foreground"])],
    )
    style.configure(
        "Status.Treeview", background=c["panel_alt"], fieldbackground=c["panel_alt"],
        foreground=c["foreground"], rowheight=round(29 * scale),
        bordercolor=c["border"], font=FONTS["body"],
    )
    style.configure(
        "Status.Treeview.Heading", background=c["panel"], foreground=c["muted"],
        font=FONTS["section"],
    )
    style.map(
        "Status.Treeview",
        background=[("selected", c["selection"])],
        foreground=[("selected", "white")],
    )
    return style
