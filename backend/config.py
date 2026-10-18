"""Model selection, chosen in Phase 0 (see logs/phase0/). Override via env vars."""

import os

TRANSCRIBER = os.getenv("TRANSCRIBER", "perceptron")
TRANSCRIBER_REASONING = os.getenv("TRANSCRIBER_REASONING", "low")
ANALYZER = os.getenv("ANALYZER", "claude")

# Frame gate (whole-frame, no homography). Diffs are computed on a small grayscale
# thumbnail; a pixel counts as changed if its value moves more than PIXEL_DELTA.
GATE_THUMB_SIZE = (320, 180)  # also the resolution used to locate changed lines
GATE_PIXEL_DELTA = int(os.getenv("GATE_PIXEL_DELTA", "25"))
GATE_CHANGED_FRACTION = float(os.getenv("GATE_CHANGED_FRACTION", "0.002"))
GATE_STILL_FRACTION = float(os.getenv("GATE_STILL_FRACTION", "0.001"))
GATE_STABLE_SECONDS = float(os.getenv("GATE_STABLE_SECONDS", "1.0"))
ANALYSIS_INTERVAL_SECONDS = float(os.getenv("ANALYSIS_INTERVAL_SECONDS", "5.0"))

# Line-level updates: when a change falls on a few known lines, re-read only those lines
# from small crops instead of transcribing the whole board.
LINE_PATCH = os.getenv("LINE_PATCH", "1") == "1"
LINE_PATCH_MAX_LINES = int(os.getenv("LINE_PATCH_MAX_LINES", "3"))
FULL_PASS_EVERY = int(os.getenv("FULL_PASS_EVERY", "5"))  # resync after this many partial passes
LINE_PAD_FRACTION = float(os.getenv("LINE_PAD_FRACTION", "0.35"))  # of line height, each side
# Changed pixels outside every known line (a new line or region) above this share -> full pass.
UNLOCALIZED_MAX_FRACTION = float(os.getenv("UNLOCALIZED_MAX_FRACTION", "0.15"))

# Gemini Live prebuilt voice (e.g. Zephyr, Puck). Sent to the client in /voice-config.
VOICE_NAME = os.getenv("VOICE_NAME", "Zephyr")
