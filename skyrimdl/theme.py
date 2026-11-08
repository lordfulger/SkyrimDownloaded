"""Light and dark looks for the window.

"System" follows Windows' own setting (Settings > Personalisation > Colours >
"Choose your app mode"). Dark mode also darkens the title bar on Windows 10/11.
"""

from __future__ import annotations

import sys

try:  # the settings code imports this module too, even where Tk isn't installed
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover
    tk = ttk = None

MODES = ("System", "Light", "Dark")

LIGHT = {
    "bg": "#f3f3f3", "fg": "#1b1b1b", "field": "#ffffff", "muted": "#5c5c5c",
    "border": "#c9c9c9", "button": "#e6e6e6", "button_hover": "#dadada",
    "select": "#cce0ff", "select_fg": "#1b1b1b", "accent": "#2563c9",
    "choose": "#fff1cc", "error": "#b00020", "done": "#1b7a1b", "off": "#8a8a8a",
    "details": "#f8f8f8", "disabled": "#a0a0a0", "trough": "#e2e2e2",
}
DARK = {
    "bg": "#1f2023", "fg": "#e8e8e8", "field": "#2a2c30", "muted": "#a3a7ad",
    "border": "#3d4046", "button": "#33363b", "button_hover": "#3f434a",
    "select": "#2e4c7d", "select_fg": "#ffffff", "accent": "#6aa4ff",
    "choose": "#4a3d17", "error": "#ff7a7a", "done": "#7bd67f", "off": "#7f848b",
    "details": "#25272b", "disabled": "#6b6f75", "trough": "#2a2c30",
}


def system_prefers_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except OSError:
        return False


def resolve(mode: str) -> str:
    """'System' -> 'Light' or 'Dark'."""
    if mode == "Dark" or (mode == "System" and system_prefers_dark()):
        return "Dark"
    return "Light"


class Theme:
    def __init__(self, root: tk.Tk, mode: str = "System"):
        self.root = root
        self.style = ttk.Style(root)
        self.mode = mode if mode in MODES else "System"
        self.colors = LIGHT

    @property
    def is_dark(self) -> bool:
        return self.colors is DARK

    def apply(self, mode: str | None = None) -> None:
        if mode is not None:
            self.mode = mode if mode in MODES else "System"
        self.colors = DARK if resolve(self.mode) == "Dark" else LIGHT
        c = self.colors
        s = self.style
        # 'clam' is the ttk theme that takes custom colours everywhere.
        s.theme_use("clam")
        s.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"],
                    bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"],
                    troughcolor=c["trough"], focuscolor=c["accent"], selectbackground=c["select"],
                    selectforeground=c["select_fg"], insertcolor=c["fg"], arrowcolor=c["fg"])
        s.map(".", foreground=[("disabled", c["disabled"])])
        s.configure("TFrame", background=c["bg"])
        s.configure("TLabel", background=c["bg"], foreground=c["fg"])
        s.configure("Muted.TLabel", foreground=c["muted"])
        s.configure("Good.TLabel", foreground=c["done"])
        if not hasattr(self, "_link_font"):
            from tkinter import font as tkfont
            self._link_font = tkfont.nametofont("TkDefaultFont").copy()
            self._link_font.configure(underline=True)
        s.configure("Link.TLabel", foreground=c["accent"], font=self._link_font)
        s.configure("Warn.TLabel", foreground=c["error"])
        s.configure("Title.TLabel", font=("TkDefaultFont", 13, "bold"))
        s.configure("TLabelframe", background=c["bg"], bordercolor=c["border"])
        s.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"])
        s.configure("TButton", background=c["button"], foreground=c["fg"], bordercolor=c["border"],
                    lightcolor=c["button"], darkcolor=c["button"], padding=(10, 4))
        s.map("TButton",
              background=[("disabled", c["bg"]), ("pressed", c["select"]), ("active", c["button_hover"])],
              foreground=[("disabled", c["disabled"])])
        s.configure("Accent.TButton", background=c["accent"], foreground="#ffffff",
                    lightcolor=c["accent"], darkcolor=c["accent"], bordercolor=c["accent"])
        s.map("Accent.TButton",
              background=[("disabled", c["bg"]), ("pressed", c["accent"]), ("active", c["accent"])],
              foreground=[("disabled", c["disabled"])])
        for widget in ("TCheckbutton", "TRadiobutton"):
            s.configure(widget, background=c["bg"], foreground=c["fg"],
                        indicatorbackground=c["field"], indicatorforeground=c["fg"])
            s.map(widget, background=[("active", c["bg"])],
                  indicatorbackground=[("selected", c["accent"]), ("disabled", c["bg"])],
                  indicatorforeground=[("selected", "#ffffff")],
                  foreground=[("disabled", c["disabled"])])
        s.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"], insertcolor=c["fg"])
        s.map("TEntry", fieldbackground=[("disabled", c["bg"])])
        s.configure("TCombobox", fieldbackground=c["field"], foreground=c["fg"], background=c["button"],
                    arrowcolor=c["fg"])
        s.map("TCombobox", fieldbackground=[("readonly", c["field"])],
              foreground=[("readonly", c["fg"])], selectbackground=[("readonly", c["field"])],
              selectforeground=[("readonly", c["fg"])])
        s.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["fg"],
                    bordercolor=c["border"], rowheight=22)
        s.map("Treeview", background=[("selected", c["select"])],
              foreground=[("selected", c["select_fg"])])
        s.configure("Treeview.Heading", background=c["button"], foreground=c["fg"],
                    bordercolor=c["border"], lightcolor=c["button"], darkcolor=c["button"])
        s.map("Treeview.Heading", background=[("active", c["button_hover"])])
        s.configure("TProgressbar", background=c["accent"], troughcolor=c["trough"],
                    bordercolor=c["border"], lightcolor=c["accent"], darkcolor=c["accent"])
        s.configure("TScrollbar", background=c["button"], troughcolor=c["bg"], bordercolor=c["bg"],
                    arrowcolor=c["fg"], lightcolor=c["button"], darkcolor=c["button"])
        s.map("TScrollbar", background=[("active", c["button_hover"])])
        s.configure("TSeparator", background=c["border"])
        # The drop-down list of a combobox is a plain Tk listbox.
        for pattern, value in (("*TCombobox*Listbox.background", c["field"]),
                               ("*TCombobox*Listbox.foreground", c["fg"]),
                               ("*TCombobox*Listbox.selectBackground", c["select"]),
                               ("*TCombobox*Listbox.selectForeground", c["select_fg"])):
            self.root.option_add(pattern, value)
        self.paint(self.root)

    def paint(self, widget: tk.Misc) -> None:
        """Colour plain Tk widgets (ttk ones follow the style) under ``widget``."""
        c = self.colors
        cls = widget.winfo_class()
        try:
            if cls in ("Tk", "Toplevel"):
                widget.configure(background=c["bg"])
                self.title_bar(widget)
            elif cls == "Text":
                bg = c["details"] if getattr(widget, "_details", False) else c["field"]
                widget.configure(background=bg, foreground=c["fg"], insertbackground=c["fg"],
                                 selectbackground=c["select"], selectforeground=c["select_fg"],
                                 highlightbackground=c["border"], highlightcolor=c["accent"])
            elif cls == "Listbox":
                widget.configure(background=c["field"], foreground=c["fg"],
                                 selectbackground=c["select"], selectforeground=c["select_fg"],
                                 highlightbackground=c["border"], highlightcolor=c["accent"])
            elif cls == "Canvas":
                widget.configure(background=c["bg"])
            elif cls == "Menu":
                widget.configure(background=c["field"], foreground=c["fg"],
                                 activebackground=c["select"], activeforeground=c["select_fg"])
            elif cls == "Treeview":
                widget.tag_configure("choose", background=c["choose"])
                widget.tag_configure("error", foreground=c["error"])
                widget.tag_configure("off", foreground=c["off"])
                widget.tag_configure("done", foreground=c["done"])
                widget.tag_configure("section", foreground=c["accent"],
                                     font=("TkDefaultFont", 10, "bold"))
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self.paint(child)

    def title_bar(self, window: tk.Misc) -> None:
        """Dark or light title bar on Windows 10 (20H1+) and 11."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            value = ctypes.c_int(1 if self.is_dark else 0)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, then old builds)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
            # Nudge Windows to redraw the frame with the new colour.
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        except Exception:
            pass
