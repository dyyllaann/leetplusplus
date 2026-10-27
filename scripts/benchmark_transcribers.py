"""Compare transcription models on the whiteboard fixtures.

Each candidate is "provider[:model[:effort]]". Runs are sequential so latencies are
not contended. Output goes through the same normalization the live pipeline uses.

Usage:
    .venv/bin/python scripts/benchmark_transcribers.py
    .venv/bin/python scripts/benchmark_transcribers.py --transcribers perceptron,gemini:gemini-3.8-flash:low --runs 3

Add a fixture by dropping <name>.png and <name>.expected.json into fixtures/.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from backend.evaluation.benchmark import Spec, aggregate, load_fixtures, score_run  # noqa: E402
from backend.models.call_log import save_call  # noqa: E402
from backend.models.schemas import ModelCall  # noqa: E402
from backend.models.transcriber import get_transcriber  # noqa: E402
from backend.pipeline import normalize_region_ids  # noqa: E402
from validate_models import print_table  # noqa: E402


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def secs(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transcribers", default="perceptron,gemini")
    parser.add_argument("--fixtures", default="fixtures")
    parser.add_argument("--runs", type=int, default=3, help="Runs per fixture (latency varies)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    fixtures = load_fixtures(ROOT / args.fixtures, ROOT)
    if not fixtures:
        print(f"no *.expected.json fixtures in {args.fixtures}")
        return 1
    log_dir = ROOT / "logs/benchmarks" / datetime.now().strftime("%Y%m%d-%H%M%S")
    specs = [Spec.parse(s) for s in args.transcribers.split(",") if s.strip()]

    rows, summary = [], {"fixtures": [f.name for f in fixtures], "runs_per_fixture": args.runs,
                         "candidates": {}}
    for spec in specs:
        print(f"\nrunning {spec.label} ...", flush=True)
        try:
            transcriber = get_transcriber(spec.provider, spec.model, spec.effort)
        except Exception as exc:  # unknown provider, missing API key, bad effort
            print(f"  error: {type(exc).__name__}: {exc}")
            summary["candidates"][spec.label] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        runs = []
        for fixture in fixtures:
            image = fixture.image.read_bytes()
            mime = mimetypes.guess_type(fixture.image.name)[0] or "image/png"
            for i in range(args.runs):
                try:
                    call = transcriber.transcribe(image, mime)
                except Exception as exc:
                    call = ModelCall(provider=spec.provider, model=transcriber.model, parsed=None,
                                     latency_s=0.0, error=f"{type(exc).__name__}: {exc}")
                save_call(log_dir, f"{spec.label.replace(':', '_')}_{fixture.name}_{i}", call)
                run = score_run(fixture, call, normalize_region_ids(call.parsed) if call.parsed else None)
                runs.append(run)
                status = run.error or (f"acc {pct(run.char_accuracy)}, bugs {run.bugs_kept}/{run.bugs_total}"
                                       + (f", CORRECTED {run.corrected}" if run.corrected else ""))
                print(f"  {fixture.name} #{i + 1}: {run.latency_s:.1f}s {status}", flush=True)
        agg = aggregate(runs)
        summary["candidates"][spec.label] = {"model": transcriber.model, **agg}
        rows.append([
            spec.label, transcriber.model, pct(agg["char_accuracy"]),
            f"{agg['bugs_kept']}/{agg['bugs_total']}",
            "FAIL" if agg["corrected_runs"] else "ok",
            pct(agg["box_iou"]), pct(agg["line_boxes"]),
            secs(agg["latency_p50"]), secs(agg["latency_max"]),
            "-" if agg["output_tokens"] is None else f"{agg['output_tokens']:.0f}",
            f"{agg['errors']}/{agg['runs']}",
        ])

    if rows:
        print(f"\n== Transcriber comparison ({len(fixtures)} fixture(s) x {args.runs} run(s)) ==")
        print_table(["candidate", "model", "char acc", "bugs kept", "literal", "box IoU",
                     "line boxes", "p50 s", "max s", "out tok", "errors"], rows)
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"raw responses: {log_dir.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
