"""Model selection, chosen in Phase 0 (see logs/phase0/). Override via env vars."""

import os

TRANSCRIBER = os.getenv("TRANSCRIBER", "perceptron")
TRANSCRIBER_REASONING = os.getenv("TRANSCRIBER_REASONING", "low")
ANALYZER = os.getenv("ANALYZER", "claude")

# Frame gate (whole-frame, no homography). Diffs are computed on a small grayscale
# thumbnail; a pixel counts as changed if its value moves more than PIXEL_DELTA.
GATE_THUMB_SIZE = (160, 90)
GATE_PIXEL_DELTA = int(os.getenv("GATE_PIXEL_DELTA", "25"))
GATE_CHANGED_FRACTION = float(os.getenv("GATE_CHANGED_FRACTION", "0.002"))
GATE_STILL_FRACTION = float(os.getenv("GATE_STILL_FRACTION", "0.001"))
GATE_STABLE_SECONDS = float(os.getenv("GATE_STABLE_SECONDS", "1.0"))
ANALYSIS_INTERVAL_SECONDS = float(os.getenv("ANALYSIS_INTERVAL_SECONDS", "5.0"))
