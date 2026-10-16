"""Global bindings that work while DCS has focus: a keyboard key (with optional Ctrl/Shift/Alt) or a
joystick / HOTAS button. One polling thread at 100 Hz, rising edge -> action; no hooks, so nothing is
ever swallowed from the game (DCS still sees the key / button too - bind something DCS does not use).

Binding text: 'key:<vk>[:ctrl][:shift][:alt]'  or  'joy:<device 0-15>:<button 1-32>'.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
winmm = ctypes.windll.winmm

VK_CTRL, VK_SHIFT, VK_ALT = 0x11, 0x10, 0x12
MODS = {"ctrl": VK_CTRL, "shift": VK_SHIFT, "alt": VK_ALT}
SKIP_VK = {0x01, 0x02, 0x04, 0x05, 0x06, VK_CTRL, VK_SHIFT, VK_ALT, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}
JOY_RETURNBUTTONS = 0x80


class JOYINFOEX(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("dwXpos", wintypes.DWORD),
                ("dwYpos", wintypes.DWORD), ("dwZpos", wintypes.DWORD), ("dwRpos", wintypes.DWORD),
                ("dwUpos", wintypes.DWORD), ("dwVpos", wintypes.DWORD), ("dwButtons", wintypes.DWORD),
                ("dwButtonNumber", wintypes.DWORD), ("dwPOV", wintypes.DWORD), ("dwReserved1", wintypes.DWORD),
                ("dwReserved2", wintypes.DWORD)]


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def joy_buttons(dev: int) -> int | None:
    ji = JOYINFOEX()
    ji.dwSize = ctypes.sizeof(ji)
    ji.dwFlags = JOY_RETURNBUTTONS
    return ji.dwButtons if winmm.joyGetPosEx(dev, ctypes.byref(ji)) == 0 else None


def key_name(vk: int) -> str:
    sc = user32.MapVirtualKeyW(vk, 0)
    buf = ctypes.create_unicode_buffer(32)
    if vk in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E):
        sc |= 0x100   # extended keys: arrows, Home, End, PgUp/Dn, Ins, Del
    n = user32.GetKeyNameTextW(sc << 16, buf, 32)
    if 0x70 <= vk <= 0x87:
        return "F%d" % (vk - 0x6F)
    return buf.value if n else "VK %d" % vk


def describe(binding: str) -> str:
    if not binding:
        return "(not set)"
    p = binding.split(":")
    if p[0] == "key" and len(p) >= 2:
        return "+".join([m.capitalize() for m in p[2:]] + [key_name(int(p[1]))])
    if p[0] == "joy" and len(p) == 3:
        return "Joystick %d button %s" % (int(p[1]) + 1, p[2])
    return binding


def parse(binding: str):
    p = (binding or "").split(":")
    if p[0] == "key" and len(p) >= 2:
        return ("key", int(p[1]), [MODS[m] for m in p[2:] if m in MODS])
    if p[0] == "joy" and len(p) == 3:
        return ("joy", int(p[1]), int(p[2]))
    return None


class Hotkeys(threading.Thread):
    """actions: {name: callback}; bindings: {name: binding text}. capture(cb) -> next key / button."""

    def __init__(self, actions: dict, bindings: dict):
        super().__init__(daemon=True, name="hotkeys")
        self.actions = actions
        self.bindings = dict(bindings)
        self._prev = {}
        self._capture = None
        self._cap_prev = None
        self._stop = threading.Event()

    def set_binding(self, name: str, binding: str):
        self.bindings[name] = binding
        self._prev.pop(name, None)

    def capture(self, cb):
        """Next newly pressed key (with held modifiers) or joystick button -> cb(binding text)."""
        self._cap_prev = self._snapshot()
        self._capture = cb

    def _snapshot(self):
        keys = {vk for vk in range(0x08, 0xFF) if vk not in SKIP_VK and key_down(vk)}
        joys = {}
        for d in range(16):
            b = joy_buttons(d)
            if b is not None:
                joys[d] = b
        return keys, joys

    def _pressed(self, name: str) -> bool:
        b = parse(self.bindings.get(name, ""))
        if not b:
            return False
        if b[0] == "key":
            return key_down(b[1]) and all(key_down(m) for m in b[2])
        btn = joy_buttons(b[1])
        return bool(btn is not None and btn & (1 << (b[2] - 1)))

    def run(self):
        while not self._stop.is_set():
            if self._capture:
                keys, joys = self._snapshot()
                pk, pj = self._cap_prev
                new_keys = keys - pk
                hit = None
                if new_keys:
                    vk = min(new_keys)
                    mods = [m for m, v in MODS.items() if key_down(v)]
                    hit = ":".join(["key", str(vk)] + mods)
                else:
                    for d, b in joys.items():
                        new = b & ~pj.get(d, 0)
                        if new:
                            hit = "joy:%d:%d" % (d, (new & -new).bit_length())
                            break
                self._cap_prev = (keys, joys)
                if hit:
                    cb, self._capture = self._capture, None
                    cb(hit)
            else:
                for name, fn in self.actions.items():
                    down = self._pressed(name)
                    if down and not self._prev.get(name):
                        try:
                            fn()
                        except Exception:
                            pass
                    self._prev[name] = down
            time.sleep(0.01)

    def stop(self):
        self._stop.set()
