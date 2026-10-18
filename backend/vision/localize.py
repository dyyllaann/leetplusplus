"""Decide whether a pass can re-read only the lines that changed.

The gate's change mask (thumbnail pixels that differ from the last analyzed frame) is
mapped onto the line boxes from the last full transcription. If the change sits on a few
known lines, those lines are cropped and re-read individually; anything else (new lines,
new regions, many lines, camera movement) falls back to a full-board transcription.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend import config
from backend.models.schemas import BBox, Transcription


@dataclass
class LineTarget:
    region_id: str
    n: int
    crop: BBox  # 0-1000 grid, the area to send to the line transcriber


@dataclass
class PassPlan:
    full: bool
    reason: str
    lines: list[LineTarget] = field(default_factory=list)


def _to_grid(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Changed pixel coordinates on the 0-1000 grid."""
    ys, xs = np.nonzero(mask)
    h, w = mask.shape
    return (xs + 0.5) * 1000 / w, (ys + 0.5) * 1000 / h


def plan_pass(mask: np.ndarray | None, transcription: Transcription | None,
              partials_since_full: int) -> PassPlan:
    if not config.LINE_PATCH:
        return PassPlan(True, "line patch disabled")
    if mask is None or transcription is None:
        return PassPlan(True, "no previous transcription")
    if partials_since_full >= config.FULL_PASS_EVERY:
        return PassPlan(True, "periodic resync")

    xs, ys = _to_grid(mask)
    if xs.size == 0:
        return PassPlan(True, "no changed pixels")

    claimed = np.zeros(xs.size, dtype=bool)
    targets: list[LineTarget] = []
    for region in transcription.regions:
        rb = region.bbox
        # Writing often continues to the right of a line, so allow the region to grow rightward.
        right = min(1000.0, rb.x2 + 0.25 * (rb.x2 - rb.x1) + 20)
        for line in region.lines:
            lb = line.bbox
            if lb is None:
                return PassPlan(True, f"no bbox for {region.id} line {line.n}")
            pad = config.LINE_PAD_FRACTION * max(lb.y2 - lb.y1, 10)
            hit = ((ys >= lb.y1 - pad) & (ys <= lb.y2 + pad)
                   & (xs >= rb.x1 - 20) & (xs <= right) & ~claimed)
            if not hit.any():
                continue
            claimed |= hit
            x1 = int(max(0, min(lb.x1, xs[hit].min()) - 20))
            x2 = int(min(1000, max(lb.x2, xs[hit].max()) + 20))
            y_pad = 0.6 * (lb.y2 - lb.y1)
            targets.append(LineTarget(region.id, line.n, BBox(
                x1=x1, y1=int(max(0, lb.y1 - y_pad)), x2=x2, y2=int(min(1000, lb.y2 + y_pad)))))

    unlocalized = 1.0 - claimed.mean()
    if unlocalized > config.UNLOCALIZED_MAX_FRACTION:
        return PassPlan(True, f"{unlocalized:.0%} of the change is outside known lines")
    if not targets:
        return PassPlan(True, "change not on any line")
    if len(targets) > config.LINE_PATCH_MAX_LINES:
        return PassPlan(True, f"{len(targets)} lines changed")
    return PassPlan(False, f"{len(targets)} line(s) changed", targets)
