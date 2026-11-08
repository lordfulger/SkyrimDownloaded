"""Scrolling helpers: mouse wheel anywhere over a scrollable area, and
middle-click scrolling like a web browser.

Middle-click scrolling: click the middle button (wheel) once and move the mouse
up or down - the further from where you clicked, the faster it scrolls; click
again (any button) or press Esc to stop. Or hold the middle button and drag,
and it stops when you let go.
"""

from __future__ import annotations

import sys
import time
import tkinter as tk

DEAD_ZONE = 10      # pixels the mouse can move before scrolling starts
TICK_MS = 25


class AutoScroll:
    def __init__(self, widget: tk.Widget, *, also: tuple[tk.Widget, ...] = ()):
        """``widget`` is what scrolls (has yview_scroll); ``also`` are widgets
        on top of it (e.g. the contents of a canvas) that should start it too."""
        self.widget = widget
        self.active = False
        self.anchor = 0
        self.moved = False
        self.pressed_at = 0.0
        self.carry = 0.0
        self._job = None
        self._old_cursor = ""
        for w in (widget, *also):
            self.attach(w)

    def attach(self, w: tk.Widget) -> None:
        w.bind("<ButtonPress-2>", self._press, add="+")
        w.bind("<ButtonRelease-2>", self._release, add="+")

    def _press(self, event):
        if self.active:
            self.stop()
            return "break"
        self.active = True
        self.moved = False
        self.pressed_at = time.monotonic()
        self.anchor = event.y_root
        self.carry = 0.0
        try:
            self._old_cursor = self.widget.cget("cursor")
            self.widget.configure(cursor="sb_v_double_arrow")
        except tk.TclError:
            pass
        top = self.widget.winfo_toplevel()
        self._binds = [
            (top, "<ButtonPress-1>", top.bind("<ButtonPress-1>", lambda e: self.stop(), add="+")),
            (top, "<ButtonPress-3>", top.bind("<ButtonPress-3>", lambda e: self.stop(), add="+")),
            (top, "<Escape>", top.bind("<Escape>", lambda e: self.stop(), add="+")),
        ]
        self._tick()
        return "break"  # don't paste (X11) or do anything else

    def _release(self, event):
        # Held and dragged (or held a while): stop when let go. A quick click keeps it on.
        if self.active and (self.moved or time.monotonic() - self.pressed_at > 0.35):
            self.stop()
        return "break"

    def _tick(self) -> None:
        if not self.active:
            return
        try:
            dy = self.widget.winfo_pointery() - self.anchor
        except tk.TclError:
            self.active = False
            return
        if abs(dy) > DEAD_ZONE:
            self.moved = True
            speed = (abs(dy) - DEAD_ZONE) / 18.0          # lines per tick
            self.carry += speed if dy > 0 else -speed
            whole = int(self.carry)
            if whole:
                self.carry -= whole
                try:
                    self.widget.yview_scroll(whole, "units")
                except tk.TclError:
                    pass
        self._job = self.widget.after(TICK_MS, self._tick)

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        if self._job:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        try:
            self.widget.configure(cursor=self._old_cursor)
        except tk.TclError:
            pass
        for w, seq, func_id in getattr(self, "_binds", []):
            try:
                w.unbind(seq, func_id)
            except tk.TclError:
                pass
        self._binds = []


def wheel_scroll(target: tk.Widget, *areas: tk.Widget) -> None:
    """Scroll ``target`` with the mouse wheel whenever the pointer is over any of
    ``areas`` (the canvas and everything inside it)."""

    def on_wheel(event):
        if getattr(event, "num", None) == 4:
            step = -3
        elif getattr(event, "num", None) == 5:
            step = 3
        else:
            delta = event.delta if sys.platform != "darwin" else event.delta * 120
            step = -int(delta / 120) * 3 if delta else 0
        if step:
            target.yview_scroll(step, "units")
        return "break"

    def bind_tree(w: tk.Widget) -> None:
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            w.bind(seq, on_wheel, add="+")
        for child in w.winfo_children():
            bind_tree(child)

    for area in (target, *areas):
        bind_tree(area)
