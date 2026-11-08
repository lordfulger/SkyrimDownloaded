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
from ..nexus import NexusClient, NexusError
from .. import appupdate, collections, mo2addon, pictures, compat, gameversion, logs, loot, nexuscache, session, sharing, updates
from ..logs import log
from ..scrolling import AutoScroll, wheel_scroll
from ..text import bbcode_to_text
from ..engine import rechoose
from ..selection import annotate, for_other_versions, human_size, human_time, visible_options


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
