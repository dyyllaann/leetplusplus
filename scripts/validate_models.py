"""Phase 0: compare analyzer candidates on a fixed whiteboard image.

Usage:
    .venv/bin/python scripts/validate_models.py
    .venv/bin/python scripts/validate_models.py --analyzers claude,gemini --use-expected-transcription
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import mimetypes
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from backend.evaluation.scoring import (  # noqa: E402
    FindingsScore, TranscriptionScore, code_lines, score_findings, score_transcription)
from backend.models.analyzer import ANALYZERS, get_analyzer  # noqa: E402
from backend.models.schemas import ModelCall, Transcription  # noqa: E402
from backend.models.transcriber import get_transcriber  # noqa: E402


def save_call(log_dir: Path, name: str, call: ModelCall) -> None:
    record = {
        "provider": call.provider, "model": call.model, "latency_s": call.latency_s,
        "input_tokens": call.input_tokens, "output_tokens": call.output_tokens,
        "error": call.error, "request": call.request, "response": call.response,
        "parsed": call.parsed.model_dump(mode="json") if call.parsed else None,
    }
    (log_dir / f"{name}.json").write_text(json.dumps(record, indent=2, default=str))


def expected_transcription(expected: dict) -> Transcription:
    return Transcription.model_validate({"regions": [{
        "id": r["id"], "type": r["type"],
        "bbox": dict(zip(("x1", "y1", "x2", "y2"), r["approx_bbox"])),
        "lines": [{"n": i, "text": t, "low_confidence_chars": []} for i, t in enumerate(r["lines"], 1)],
    } for r in expected["regions"]]})


def fmt_tokens(call: ModelCall) -> tuple[str, str]:
    return (str(call.input_tokens) if call.input_tokens is not None else "-",
            str(call.output_tokens) if call.output_tokens is not None else "-")


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    line = "+".join("-" * (w + 2) for w in widths)
    print("+" + line + "+")
    print("| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |")
    print("+" + line + "+")
    for r in rows:
        print("| " + " | ".join(c.ljust(w) for c, w in zip(r, widths)) + " |")
    print("+" + line + "+")


def report_transcription(call: ModelCall[Transcription], score: TranscriptionScore | None) -> None:
    print(f"\n== Transcription ({call.provider} {call.model}) ==")
    if call.error:
        print(f"ERROR: {call.error}")
        return
    for ln in code_lines(call.parsed):
        print(f"   {ln}")
    tin, tout = fmt_tokens(call)
    verdict = "FAIL (corrected the code)" if score.failed else "ok (errors preserved)"
    print(f"char accuracy (code, whitespace-insensitive): {score.char_accuracy:.1%}")
    print(f"preserve checks: {len(score.preserved)}/{len(score.preserved) + len(score.missing)} present,"
          f" fixed={score.fixed or 'none'} -> {verdict}")
    print(f"latency {call.latency_s:.1f}s, tokens in/out {tin}/{tout}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", default="fixtures/whiteboard_1.png")
    parser.add_argument("--expected", default="fixtures/whiteboard_1.expected.json")
    parser.add_argument("--analyzers", default=",".join(ANALYZERS))
    parser.add_argument("--use-expected-transcription", action="store_true",
                        help="Feed analyzers the ground-truth lines instead of Perceptron's output")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    image_path = ROOT / args.image
    image = image_path.read_bytes()
    mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
    expected = json.loads((ROOT / args.expected).read_text())

    log_dir = ROOT / "logs/phase0" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)

    # 1. Literal transcription (always run, so it is scored even if analyzers use ground truth).
    t_call = get_transcriber("perceptron").transcribe(image, mime)
    save_call(log_dir, "transcription_perceptron", t_call)
    t_score = score_transcription(t_call.parsed, expected) if t_call.parsed else None
    report_transcription(t_call, t_score)

    if args.use_expected_transcription:
        transcription, source = expected_transcription(expected), "ground truth"
    elif t_call.parsed:
        transcription, source = t_call.parsed, "perceptron"
    else:
        print("\nTranscription failed; falling back to ground-truth lines for analyzers.")
        transcription, source = expected_transcription(expected), "ground truth (fallback)"

    # 2. Analyzer candidates, sequential so latency numbers are not contended.
    rows, summary = [], {"log_dir": str(log_dir), "transcription_source": source,
                         "transcription": dataclasses.asdict(t_score) if t_score else None,
                         "analyzers": {}}
    for name in [n.strip() for n in args.analyzers.split(",") if n.strip()]:
        print(f"\nrunning analyzer: {name} ...", flush=True)
        try:
            analyzer = get_analyzer(name)
            a_call = analyzer.analyze(image, mime, transcription, expected["problem"])
        except Exception as exc:  # e.g. missing API key at construction
            a_call = ModelCall(provider=name, model="?", parsed=None, latency_s=0.0,
                               error=f"{type(exc).__name__}: {exc}")
        save_call(log_dir, f"analyzer_{name}", a_call)

        tin, tout = fmt_tokens(a_call)
        if a_call.parsed is None:
            rows.append([name, a_call.model, "ERR", "-", "-", "-", "-", "-",
                         f"{a_call.latency_s:.1f}", tin, tout])
            print(f"  error: {a_call.error}")
            summary["analyzers"][name] = {"model": a_call.model, "error": a_call.error}
            continue

        s: FindingsScore = score_findings(a_call.parsed.findings, expected)
        rows.append([
            name, a_call.model,
            f"{len(s.required_found)}/{s.required_total}",
            f"{len(s.tier_correct)}/{s.required_total}",
            ",".join(s.acceptable_found) or "-",
            str(len(s.fp_serious)), str(len(s.fp_minor)),
            str(len(a_call.parsed.findings)),
            f"{a_call.latency_s:.1f}", tin, tout,
        ])
        for f in a_call.parsed.findings:
            print(f"  [t{f.tier} L{f.line} c={f.confidence:.2f}] {f.category}: {f.message}")
        summary["analyzers"][name] = {
            "model": a_call.model, "latency_s": a_call.latency_s,
            "input_tokens": a_call.input_tokens, "output_tokens": a_call.output_tokens,
            "recall": s.recall, "required_found": s.required_found, "tier_correct": s.tier_correct,
            "acceptable_found": s.acceptable_found,
            "fp_serious": [f.model_dump() for f in s.fp_serious],
            "fp_minor": [f.model_dump() for f in s.fp_minor],
        }

    print(f"\n== Analyzer comparison (transcription source: {source}) ==")
    print_table(
        ["analyzer", "model", "recall", "tier ok", "acceptable", "FP t1-2", "FP t3-4",
         "findings", "latency s", "in tok", "out tok"],
        rows,
    )
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"raw responses: {log_dir.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
