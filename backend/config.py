"""Model selection, chosen in Phase 0 (see logs/phase0/). Override via env vars."""

import os

CORS_ORIGINS = [
	origin.strip().rstrip("/")
	for origin in os.getenv(
		"CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
	).split(",")
	if origin.strip()
]

# Provider per role: perceptron | gemini | claude (backend/models/providers).
# *_MODEL empty = that provider's default model. *_EFFORT: none | low | medium | high.
TRANSCRIBER = os.getenv("TRANSCRIBER", "perceptron")
TRANSCRIBER_MODEL = os.getenv("TRANSCRIBER_MODEL", "")
TRANSCRIBER_EFFORT = os.getenv("TRANSCRIBER_EFFORT", "low")
ANALYZER = os.getenv("ANALYZER", "claude")
ANALYZER_MODEL = os.getenv("ANALYZER_MODEL", "")
ANALYZER_EFFORT = os.getenv("ANALYZER_EFFORT", "medium")

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


# Voice agent (Gemini Live, audio only). Model ID per ai.google.dev/gemini-api/docs/live-api/capabilities.
VOICE_MODEL = os.getenv("VOICE_MODEL", "gemini-3.8-live")
# Prebuilt voice (list: ai.google.dev/gemini-api/docs/speech-generation#voices). Empty = model default.
VOICE_NAME = os.getenv("VOICE_NAME", "Achird")
# Silence that ends a candidate turn for Gemini's speech detection (it only transcribes and
# speaks; Claude in voice/brain.py decides whether to reply at all).
VOICE_SILENCE_MS = int(os.getenv("VOICE_SILENCE_MS", "500"))
# Interviewer brain (Claude decides what to say; Gemini Live only speaks it).
BRAIN_MODEL = os.getenv("BRAIN_MODEL", "claude-opus-5-5")
BRAIN_EFFORT = os.getenv("BRAIN_EFFORT", "low")
