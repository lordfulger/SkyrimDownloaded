"""Shared imports, constants and small helpers for the window."""

from __future__ import annotations

from __future__ import annotations

import gc
import os
import queue
import sys
import re
import threading
import time
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import __version__
from ..config import Settings, choices_path, load_choices, save_choices
from ..engine import (QUEUED, DONE, missing_requirements, FAILED, SENT, SKIPPED, STOPPED, WORKING, Job, ModPlan, Runner,
                     jobs_for, resolve, summary)
from ..links import parse_list
from .. import finder
from .. import theme as theme_mod
from ..managers import ManagerError, make_target
from ..nexus import AuthError, NexusClient, NexusError
from .. import appupdate, collections, mo2addon, pictures, compat, gameversion, logs, loot, nexuscache, session, sharing, updates
from ..logs import log
from ..scrolling import AutoScroll, wheel_scroll
from ..text import bbcode_to_text
from ..engine import rechoose
from ..selection import (TEXTURE_SIZES, annotate, for_other_versions, human_size, human_time, prefer_texture,
                         pick_like, prefer_variants, primary_file, texture_sizes, visible_options)


NO_TEXTURE_PREF = "Any size"
SHOW_FILTERS = ["Show: all mods", "Still to choose", "Problems (errors, warnings)", "New files on Nexus",
                "Left out", "Patches ticked by the app"]
API_KEY_PAGE = "https://www.nexusmods.com/settings/api-keys"
ON, OFF = "\u2611", "\u2610"  # ☑ ☐
# A Nexus personal API key: one long run of base64-ish characters, no spaces.
_KEY_SHAPE = re.compile(r"^[A-Za-z0-9+/=_\-]{40,400}$")
CLIPBOARD_WAIT_MS = 5 * 60 * 1000


def file_status(opt, suggested: str | None = None) -> str:
    bits = []
    if suggested:
        bits.append("\u2605 suggested patch")
    if opt.is_primary:
        bits.append("primary")
    if opt.fit.status == "ok" and opt.fit.note:
        bits.append(opt.fit.note)
    elif opt.fit.status == "other":
        bits.append(f"{opt.fit.note} (not your version)")
    elif opt.fit.note:
        bits.append(opt.fit.note)
    return " \u00b7 ".join(bits)


#: Sizes of the app's windows, kept between runs (settings.window_sizes): {window: "WxH" or "zoomed"}.
WINDOW_SIZES: dict = {}


def remember_size(win, key: str, default: str) -> None:
    """Open a window at the size it had last time (or maximized), and remember changes.
    It can be resized and maximized like any window."""
    win.resizable(True, True)
    win.minsize(560, 380)
    size = WINDOW_SIZES.get(key) or default
    if size == "zoomed":
        win.geometry(default)
        win.after(50, lambda: _zoom(win))
    else:
        win.geometry(size)

    def note(event=None):
        if event is not None and event.widget is not win:
            return
        try:
            WINDOW_SIZES[key] = "zoomed" if win.state() == "zoomed" else win.geometry().split("+")[0]
        except tk.TclError:
            pass
    win.bind("<Configure>", note, add="+")


def _zoom(win) -> None:
    try:
        win.state("zoomed")
    except tk.TclError:
        try:
            win.attributes("-zoomed", True)
        except tk.TclError:
            pass


def link_label(parent, text: str, url: str):
    """A clickable link that opens ``url`` in the browser."""
    label = ttk.Label(parent, text=text, style="Link.TLabel", cursor="hand2")
    if url:
        label.bind("<Button-1>", lambda e: webbrowser.open(url))
    return label


def pick_one(master, title: str, prompt: str, items: list, describe):
    """A small list to choose one item from; returns the item or None."""
    win = tk.Toplevel(master)
    win.title(title)
    win.geometry("720x320")
    win.transient(master)
    win.grab_set()
    ttk.Label(win, text=prompt, wraplength=680).pack(anchor="w", padx=12, pady=(12, 6))
    box = tk.Listbox(win, activestyle="dotbox", relief="flat", highlightthickness=1)
    for item in items:
        box.insert("end", describe(item))
    box.pack(fill="both", expand=True, padx=12)
    box.selection_set(0)
    result = {"item": None}

    def ok(_event=None):
        sel = box.curselection()
        if sel:
            result["item"] = items[sel[0]]
        win.destroy()

    btns = ttk.Frame(win)
    btns.pack(fill="x", padx=12, pady=12)
    ttk.Button(btns, text="Use this one", command=ok).pack(side="right")
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right", padx=6)
    box.bind("<Double-1>", ok)
    box.bind("<Return>", ok)
    if getattr(master, "_theme", None):
        master._theme.paint(win)
    win.wait_window()
    return result["item"]


__all__ = [n for n in dir() if not n.startswith("__")] + ["__version__"]
