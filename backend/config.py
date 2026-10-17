"""Model selection, chosen in Phase 0 (see logs/phase0/). Override via env vars."""

import os

TRANSCRIBER = os.getenv("TRANSCRIBER", "perceptron")
TRANSCRIBER_REASONING = os.getenv("TRANSCRIBER_REASONING", "low")
ANALYZER = os.getenv("ANALYZER", "claude")
