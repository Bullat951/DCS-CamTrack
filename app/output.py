"""Pose -> opentrack's "UDP over network" input: 6 little-endian doubles x, y, z (cm), yaw, pitch, roll (deg)."""
from __future__ import annotations

import socket
import struct

PACK = struct.Struct("<6d")
ORDER = ("x", "y", "z", "yaw", "pitch", "roll")


def pack(pose: dict) -> bytes:
    return PACK.pack(*(float(pose[a]) for a in ORDER))


class OpentrackUdp:
    def __init__(self, host: str = "127.0.0.1", port: int = 4242):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, pose: dict) -> None:
        try:
            self.sock.sendto(pack(pose), self.addr)
        except OSError:
            pass  # opentrack not listening yet - never stop tracking for it

    def close(self):
        self.sock.close()
