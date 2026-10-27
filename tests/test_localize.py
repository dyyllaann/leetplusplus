import asyncio
import io

import numpy as np
from PIL import Image

from backend import config, pipeline
from backend.models.schemas import LineReading, ModelCall, Transcription
from backend.session.state import Session
from backend.vision.localize import plan_pass

H, W = 180, 320  # mask shape matches config.GATE_THUMB_SIZE (w, h)


def board(with_line_boxes=True):
    def line(n, y):
        d = {"n": n, "text": f"line {n}", "low_confidence_chars": []}
        if with_line_boxes:
            d["bbox"] = {"x1": 100, "y1": y, "x2": 500, "y2": y + 50}
        return d
    return Transcription.model_validate({"regions": [{
        "id": "code_1", "type": "code", "bbox": {"x1": 100, "y1": 100, "x2": 600, "y2": 400},
        "lines": [line(1, 100), line(2, 200), line(3, 300)]}]})


def mask_at(*points):
    """points on the 0-1000 grid -> boolean mask with a small blob at each."""
    m = np.zeros((H, W), dtype=bool)
    for x, y in points:
        r, c = int(y / 1000 * H), int(x / 1000 * W)
        m[r - 1:r + 2, c - 2:c + 3] = True
    return m


def test_change_on_one_line_reads_only_that_line():
    plan = plan_pass(mask_at((300, 225)), board(), 0)
    assert not plan.full and [(t.region_id, t.n) for t in plan.lines] == [("code_1", 2)]


def test_text_appended_to_the_right_of_a_line_still_maps_to_it():
    plan = plan_pass(mask_at((560, 325)), board(), 0)
    assert not plan.full and plan.lines[0].n == 3 and plan.lines[0].crop.x2 >= 560


def test_new_line_below_the_code_needs_full_pass():
    assert plan_pass(mask_at((300, 600)), board(), 0).full


def test_missing_line_boxes_or_periodic_resync_need_full_pass():
    assert plan_pass(mask_at((300, 225)), board(with_line_boxes=False), 0).full
    assert plan_pass(mask_at((300, 225)), board(), config.FULL_PASS_EVERY).full


def test_too_many_lines_need_full_pass(monkeypatch):
    monkeypatch.setattr(config, "LINE_PATCH_MAX_LINES", 2)
    assert plan_pass(mask_at((300, 125), (300, 225), (300, 325)), board(), 0).full


class LineOnlyTranscriber:
    def __init__(self, text):
        self.text = text

    def transcribe(self, image, mime):
        raise AssertionError("full transcription should not run")

    def transcribe_line(self, image, mime):
        return ModelCall(provider="fake", model="fake",
                         parsed=LineReading(text=self.text, low_confidence_chars=[]), latency_s=0.0)


def frame_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (1280, 720), "white").save(buf, "JPEG")
    return buf.getvalue()


def test_partial_pass_patches_only_the_changed_line(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.session.state.LOG_ROOT", tmp_path)
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(board(), [])
    plan = plan_pass(mask_at((300, 225)), s.raw_transcription, 0)
    patched = asyncio.run(pipeline.read_changed_lines(
        s, LineOnlyTranscriber("x = y + 1"), frame_bytes(), plan, 1))
    assert [ln.text for ln in patched.regions[0].lines] == ["line 1", "x = y + 1", "line 3"]


def test_blank_line_read_signals_structure_change(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.session.state.LOG_ROOT", tmp_path)
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(board(), [])
    plan = plan_pass(mask_at((300, 225)), s.raw_transcription, 0)
    assert asyncio.run(pipeline.read_changed_lines(
        s, LineOnlyTranscriber("  "), frame_bytes(), plan, 1)) is None


def test_run_pass_partial_updates_state_and_counts(tmp_path, monkeypatch):
    from backend.models.schemas import AnalysisResult

    class FakeAnalyzer:
        def analyze(self, image, mime, transcription, problem):
            return ModelCall(provider="fake", model="fake", latency_s=0.0,
                             parsed=AnalysisResult(findings=[], transcription_corrections=[], region_rewrites=[]))

    monkeypatch.setattr("backend.session.state.LOG_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "models", lambda: (LineOnlyTranscriber("x = y + 1"), FakeAnalyzer()))
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(board(), [])
    plan = plan_pass(mask_at((300, 225)), s.raw_transcription, 0)
    events = []

    async def emit(e):
        events.append(e)

    assert asyncio.run(pipeline.run_pass(s, frame_bytes(), "image/jpeg", emit, plan))
    assert s.transcription.regions[0].lines[1].text == "x = y + 1"
    assert s.partials_since_full == 1 and not s.need_full
    assert [e["analysisPending"] for e in events if e["type"] == "boardState"] == [True, False]


def test_line_patch_off_sends_original_request_format(monkeypatch):
    from backend.models import prompts, schemas
    from backend.models.providers import Provider
    from backend.models.transcriber import Transcriber

    seen = {}

    class FakeProvider(Provider):
        name, default_model = "fake", "fake-1"

        def structured(self, **kw):
            seen.update(kw)
            parsed = kw["schema"].model_validate({"regions": [{
                "id": "code_1", "type": "code", "bbox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1},
                "lines": [{"n": 1, "text": "x", "low_confidence_chars": []}]}]})
            return ModelCall(provider="fake", model="fake", parsed=parsed, latency_s=0.0)

    monkeypatch.setattr(config, "LINE_PATCH", False)
    call = Transcriber(FakeProvider()).transcribe(b"", "image/jpeg")
    assert seen["schema"] is schemas.TranscriptionNoBox
    assert seen["system"] == prompts.TRANSCRIBE_SYSTEM and "every line its own" not in seen["system"]
    assert isinstance(call.parsed, Transcription) and call.parsed.regions[0].lines[0].bbox is None

    monkeypatch.setattr(config, "LINE_PATCH", True)
    Transcriber(FakeProvider()).transcribe(b"", "image/jpeg")
    assert seen["schema"] is schemas.Transcription
