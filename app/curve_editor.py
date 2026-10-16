"""Curve editor widget: drag points, double-click to add, right-click to delete; live dot = your head now."""
from __future__ import annotations

import tkinter as tk

import curves as cm

BG, GRID, AXIS, LINE, PT, DOT, TXT = "#1e1e1e", "#2c2c2a", "#555", "#4c9be8", "#e8e8e8", "#4cc38a", "#8a8a8a"


class CurveEditor(tk.Canvas):
    W, H, PAD = 380, 230, 34

    def __init__(self, parent, on_change):
        super().__init__(parent, width=self.W, height=self.H, bg=BG, highlightthickness=0)
        self.on_change = on_change
        self.points: list[list[float]] = [[10.0, 10.0]]
        self.full_scale = 90.0
        self.unit = "deg"
        self.live: float | None = None
        self._drag = None
        self._xmax = self._ymax = 1.0
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", self._add)
        self.bind("<Button-3>", self._delete)

    def set_curve(self, points, full_scale: float, unit: str):
        self.points = sorted(list(map(float, p)) for p in points) or [[10.0, 10.0]]
        self.full_scale, self.unit = float(full_scale), unit
        self._ranges()
        self.draw()

    def set_live(self, head_abs: float | None):
        self.live = head_abs
        self.draw()

    # ------------------------------------------------------------ geometry
    def _ranges(self):
        last_x = max(p[0] for p in self.points)
        self._xmax = max(last_x * 1.25, 10.0)
        self._ymax = max(max(p[1] for p in self.points), self.full_scale) * 1.08

    def _px(self, x, y):
        iw, ih = self.W - self.PAD - 8, self.H - self.PAD - 8
        return self.PAD + x / self._xmax * iw, 8 + ih - y / self._ymax * ih

    def _val(self, px, py):
        iw, ih = self.W - self.PAD - 8, self.H - self.PAD - 8
        return max(0.0, (px - self.PAD) / iw * self._xmax), max(0.0, (8 + ih - py) / ih * self._ymax)

    # ------------------------------------------------------------ drawing
    def draw(self):
        self.delete("all")
        for f in (0.25, 0.5, 0.75, 1.0):
            x, _ = self._px(self._xmax * f, 0)
            _, y = self._px(0, self._ymax * f)
            self.create_line(x, 8, x, self.H - self.PAD, fill=GRID)
            self.create_line(self.PAD, y, self.W - 8, y, fill=GRID)
            self.create_text(x, self.H - self.PAD + 10, text="%.0f" % (self._xmax * f), fill=TXT, font=("Segoe UI", 8))
            self.create_text(self.PAD - 4, y, text="%.0f" % (self._ymax * f), fill=TXT, anchor="e", font=("Segoe UI", 8))
        x0, y0 = self._px(0, 0)
        self.create_line(x0, y0, self.W - 8, y0, fill=AXIS)
        self.create_line(x0, y0, x0, 8, fill=AXIS)
        _, yfs = self._px(0, self.full_scale)
        self.create_line(self.PAD, yfs, self.W - 8, yfs, fill="#7a5a2a", dash=(4, 3))
        self.create_text(self.W - 10, yfs - 7, text="DCS axis end", fill="#b08040", anchor="e", font=("Segoe UI", 8))
        self.create_text(self.W - 10, self.H - 8, text="head (%s)" % self.unit, fill=TXT, anchor="e", font=("Segoe UI", 8))
        self.create_text(self.PAD + 2, 8, text="view (%s)" % self.unit, fill=TXT, anchor="nw", font=("Segoe UI", 8))
        seg = []
        for i in range(101):
            x = self._xmax * i / 100
            seg += list(self._px(x, cm.evaluate(self.points, x)))
        self.create_line(*seg, fill=LINE, width=2)
        for x, y in self.points:
            px, py = self._px(x, y)
            self.create_oval(px - 4, py - 4, px + 4, py + 4, fill=PT, outline="")
        if self.live is not None:
            lx = min(self.live, self._xmax)
            px, py = self._px(lx, cm.evaluate(self.points, lx))
            self.create_oval(px - 5, py - 5, px + 5, py + 5, outline=DOT, width=2)

    # ------------------------------------------------------------ editing
    def _nearest(self, ex, ey, r=9):
        best, bd = None, r * r
        for i, (x, y) in enumerate(self.points):
            px, py = self._px(x, y)
            d = (px - ex) ** 2 + (py - ey) ** 2
            if d <= bd:
                best, bd = i, d
        return best

    def _press(self, e):
        self._drag = self._nearest(e.x, e.y)

    def _move(self, e):
        if self._drag is None:
            return
        x, y = self._val(e.x, e.y)
        i = self._drag                         # points are kept sorted: a point stays between its neighbours
        lo = self.points[i - 1][0] + 0.1 if i > 0 else 0.1
        hi = self.points[i + 1][0] - 0.1 if i + 1 < len(self.points) else self._xmax * 2
        self.points[i] = [round(min(max(x, lo), hi), 2), round(y, 2)]
        self.draw()

    def _release(self, _e):
        if self._drag is not None:
            self._drag = None
            self._ranges()
            self.draw()
            self.on_change(self.points)

    def _add(self, e):
        x, y = self._val(e.x, e.y)
        if x <= 0.1:
            return
        self.points = sorted(self.points + [[round(x, 2), round(y, 2)]])
        self._ranges()
        self.draw()
        self.on_change(self.points)

    def _delete(self, e):
        i = self._nearest(e.x, e.y)
        if i is not None and len(self.points) > 1:
            del self.points[i]
            self._ranges()
            self.draw()
            self.on_change(self.points)
