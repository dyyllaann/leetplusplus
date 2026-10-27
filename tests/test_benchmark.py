from pathlib import Path

from backend.evaluation.benchmark import Spec, aggregate, load_fixtures, score_run
from backend.evaluation.scoring import code_box_iou, line_box_coverage
from backend.models.schemas import ModelCall, Transcription

ROOT = Path(__file__).parents[1]
FIXTURE = load_fixtures(ROOT / "fixtures", ROOT)[0]
LINES = FIXTURE.expected["regions"][0]["lines"]


def transcription(lines, bbox=(465, 185, 790, 790), line_boxes=True):
    x1, y1, x2, y2 = bbox
    return Transcription.model_validate({"regions": [{
        "id": "code_1", "type": "code", "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "lines": [{"n": i, "text": t, "low_confidence_chars": [],
                   "bbox": {"x1": x1, "y1": y1 + i, "x2": x2, "y2": y1 + i + 1} if line_boxes else None}
                  for i, t in enumerate(lines, 1)]}]})


def ok_call(latency=1.0):
    return ModelCall(provider="fake", model="m", parsed=None, latency_s=latency, output_tokens=100)


def test_spec_parse_fills_defaults():
    assert Spec.parse("gemini") == Spec("gemini", None, "low")
    assert Spec.parse("gemini:gemini-3.8-flash:medium") == Spec("gemini", "gemini-3.8-flash", "medium")
    assert Spec.parse("claude::high").label == "claude:high"


def test_load_fixtures_finds_image_and_expected():
    assert FIXTURE.name == "whiteboard_1" and FIXTURE.image.exists()


def test_box_scores():
    exact = transcription(LINES)
    assert code_box_iou(exact, FIXTURE.expected) == 1.0
    assert code_box_iou(transcription(LINES, bbox=(0, 0, 100, 100)), FIXTURE.expected) == 0.0
    assert line_box_coverage(exact) == 1.0
    assert line_box_coverage(transcription(LINES, line_boxes=False)) == 0.0


def test_score_run_flags_corrected_code():
    fixed = [ln.replace("str2.split", "str2.join") for ln in LINES]
    run = score_run(FIXTURE, ok_call(), transcription(fixed))
    assert run.corrected == ["P1"] and run.char_accuracy < 1.0

    exact = score_run(FIXTURE, ok_call(), transcription(LINES))
    assert exact.corrected == [] and exact.bugs_kept == exact.bugs_total == 3


def test_aggregate_counts_errors_and_ignores_them_in_scores():
    runs = [score_run(FIXTURE, ok_call(1.0), transcription(LINES)),
            score_run(FIXTURE, ok_call(3.0), transcription(LINES)),
            score_run(FIXTURE, ModelCall(provider="fake", model="m", parsed=None, latency_s=9.0,
                                         error="boom"), None)]
    agg = aggregate(runs)
    assert agg["runs"] == 3 and agg["errors"] == 1
    assert agg["char_accuracy"] == 1.0 and agg["corrected_runs"] == 0
    assert agg["latency_p50"] == 3.0 and agg["latency_max"] == 3.0  # failed run's latency excluded
    assert agg["bugs_kept"] == agg["bugs_total"] == 6
