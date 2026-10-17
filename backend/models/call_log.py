"""Write every model request/response to disk for debugging and demo replay."""

from __future__ import annotations

import json
from pathlib import Path

from backend.models.schemas import ModelCall


def save_call(log_dir: Path, name: str, call: ModelCall) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "provider": call.provider, "model": call.model, "latency_s": call.latency_s,
        "input_tokens": call.input_tokens, "output_tokens": call.output_tokens,
        "error": call.error, "request": call.request, "response": call.response,
        "parsed": call.parsed.model_dump(mode="json") if call.parsed else None,
    }
    (log_dir / f"{name}.json").write_text(json.dumps(record, indent=2, default=str))
