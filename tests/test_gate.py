import numpy as np

from backend.vision.gate import FrameGate

BLANK = np.full((90, 160), 200, dtype=np.int16)


def with_stroke(base, rows=slice(40, 45), cols=slice(20, 80)):
    img = base.copy()
    img[rows, cols] = 20
    return img


def test_first_frame_needs_stability_before_ready():
    gate = FrameGate()
    assert not gate.update(BLANK, 0.0).ready
    r = gate.update(BLANK, 1.2)
    assert r.changed and r.stable and r.ready


def test_unchanged_board_is_not_ready_after_analysis():
    gate = FrameGate()
    gate.update(BLANK, 0.0)
    gate.mark_analyzed(BLANK)
    r = gate.update(BLANK, 5.0)
    assert r.stable and not r.changed


def test_new_writing_waits_for_stillness():
    gate = FrameGate()
    gate.update(BLANK, 0.0)
    gate.mark_analyzed(BLANK)
    written = with_stroke(BLANK)
    r = gate.update(written, 2.0)
    assert r.changed and not r.stable
    assert gate.update(written, 2.5).ready is False
    assert gate.update(written, 3.1).ready is True


def test_reset_analyzed_retries_same_frame():
    gate = FrameGate()
    gate.update(BLANK, 0.0)
    gate.mark_analyzed(BLANK)
    gate.reset_analyzed()
    assert gate.update(BLANK, 2.0).ready
