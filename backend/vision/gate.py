"""Whole-frame change/stability gate. Pure local pixel math, no model calls.

A frame is worth analyzing when it differs from the last analyzed frame
(changed) and has stopped moving for GATE_STABLE_SECONDS (stable).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from backend import config


def thumbnail(image: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(image)) as im:
        small = im.convert("L").resize(config.GATE_THUMB_SIZE, Image.BILINEAR)
    return np.asarray(small, dtype=np.int16)


def changed_fraction(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b) > config.GATE_PIXEL_DELTA))


@dataclass
class GateResult:
    changed: bool
    stable: bool

    @property
    def ready(self) -> bool:
        return self.changed and self.stable


class FrameGate:
    def __init__(self) -> None:
        self._prev: np.ndarray | None = None
        self._still_since: float | None = None
        self._last_analyzed: np.ndarray | None = None

    def update(self, thumb: np.ndarray, now: float) -> GateResult:
        if self._prev is None or changed_fraction(thumb, self._prev) > config.GATE_STILL_FRACTION:
            self._still_since = now
        self._prev = thumb

        stable = now - self._still_since >= config.GATE_STABLE_SECONDS
        changed = (self._last_analyzed is None
                   or changed_fraction(thumb, self._last_analyzed) > config.GATE_CHANGED_FRACTION)
        return GateResult(changed=changed, stable=stable)

    def changed_mask(self, thumb: np.ndarray) -> np.ndarray | None:
        """Pixels that differ from the last analyzed frame, or None if there is none."""
        if self._last_analyzed is None:
            return None
        return np.abs(thumb - self._last_analyzed) > config.GATE_PIXEL_DELTA

    def mark_analyzed(self, thumb: np.ndarray) -> None:
        self._last_analyzed = thumb

    def reset_analyzed(self) -> None:
        """Forget the last analyzed frame so the next stable frame is retried."""
        self._last_analyzed = None
