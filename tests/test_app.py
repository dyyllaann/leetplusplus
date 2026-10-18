"""End-to-end WebSocket flow with fake models (no network)."""

import base64
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import config, pipeline
from backend.models.schemas import AnalysisResult, Finding, ModelCall, Transcription

FRAME = "data:image/png;base64," + base64.b64encode(
    (Path(__file__).parents[1] / "fixtures/whiteboard_1.png").read_bytes()).decode()

T = Transcription.model_validate({"regions": [{
    "id": "code_1", "type": "code", "bbox": {"x1": 0, "y1": 0, "x2": 500, "y2": 500},
    "lines": [{"n": 1, "text": "str2 = str2.split('');", "low_confidence_chars": []}]}]})


class FakeTranscriber:
    def transcribe(self, image, mime):
        return ModelCall(provider="fake", model="fake", parsed=T, latency_s=0.0)


class FakeAnalyzer:
    def analyze(self, image, mime, transcription, problem):
        assert "Two Sum" in problem
        result = AnalysisResult(findings=[Finding(
            tier=2, category="logic", line=1, region_id="code_1", confidence=0.9, message="m")],
            transcription_corrections=[], region_rewrites=[])
        return ModelCall(provider="fake", model="fake", parsed=result, latency_s=0.0)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "models", lambda: (FakeTranscriber(), FakeAnalyzer()))
    monkeypatch.setattr(config, "GATE_STABLE_SECONDS", 0.0)
    monkeypatch.setattr("backend.session.state.LOG_ROOT", tmp_path)
    return TestClient(app_module.app)


def test_unknown_problem_404(client):
    assert client.post("/sessions", json={"problemId": "nope"}).status_code == 404


def test_frame_produces_board_state(client):
    sid = client.post("/sessions", json={"problemId": "two-sum"}).json()["sessionId"]
    with client.websocket_connect(f"/sessions/{sid}/ws") as ws:
        ws.send_json({"type": "frame", "capturedAt": "t", "imageData": FRAME})
        events = []
        deadline = time.time() + 5
        while time.time() < deadline:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "boardState" and not ev["analysisPending"]:
                break
    types = [e["type"] for e in events]
    assert types[0] == "gate" and "boardState" in types
    state = events[-1]
    assert state["regions"][0]["lines"][0]["text"] == "str2 = str2.split('');"
    assert state["findings"][0]["severity"] == 2
    assert client.get(f"/sessions/{sid}").json()["pass"] == 1


def test_bad_frame_reports_error(client):
    sid = client.post("/sessions", json={"problemId": "two-sum"}).json()["sessionId"]
    with client.websocket_connect(f"/sessions/{sid}/ws") as ws:
        ws.send_json({"type": "frame", "imageData": "not a data url"})
        ev = ws.receive_json()
    assert ev["stage"] == "error"


def test_problems_and_debug_page(client):
    ids = [p["id"] for p in client.get("/problems").json()]
    assert "two-sum" in ids
    assert "getUserMedia" in client.get("/debug/camera").text


def test_region_ids_are_normalized_by_type_and_position():
    t = Transcription.model_validate({"regions": [
        {"id": ",", "type": "code", "bbox": {"x1": 0, "y1": 500, "x2": 10, "y2": 600}, "lines": []},
        {"id": "code_block", "type": "code", "bbox": {"x1": 0, "y1": 100, "x2": 10, "y2": 200}, "lines": []},
        {"id": "ex", "type": "examples", "bbox": {"x1": 0, "y1": 300, "x2": 10, "y2": 400}, "lines": []},
    ]})
    assert [r.id for r in pipeline.normalize_region_ids(t).regions] == ["code_1", "examples_1", "code_2"]


def test_unchanged_board_text_skips_analyzer(monkeypatch, tmp_path):
    import asyncio
    from backend.session.state import Session

    calls = []

    class CountingAnalyzer(FakeAnalyzer):
        def analyze(self, *a):
            calls.append(1)
            return super().analyze(*a)

    monkeypatch.setattr(pipeline, "models", lambda: (FakeTranscriber(), CountingAnalyzer()))
    monkeypatch.setattr("backend.session.state.LOG_ROOT", tmp_path)
    s = Session(id="s", problem_id="two-sum", problem_text="Two Sum")

    async def emit(e):
        pass

    for _ in range(3):
        assert asyncio.run(pipeline.run_pass(s, b"img", "image/png", emit))
    assert len(calls) == 1 and s.pass_count == 1


def test_line_numbers_are_reassigned():
    t = Transcription.model_validate({"regions": [{"id": "x", "type": "code",
        "bbox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1},
        "lines": [{"n": 1, "text": t, "low_confidence_chars": []} for t in ("a", "b", "c")]}]})
    assert [ln.n for ln in pipeline.normalize_region_ids(t).regions[0].lines] == [1, 2, 3]


def test_analyzer_corrections_patch_board_state_and_keep_skip_working(monkeypatch, tmp_path):
    import asyncio
    from backend.models.schemas import Correction
    from backend.session.state import Session

    calls = []

    class CorrectingAnalyzer:
        def analyze(self, image, mime, transcription, problem):
            calls.append(1)
            result = AnalysisResult(findings=[], transcription_corrections=[
                Correction(region_id="code_1", line=1, text="str2 = str2.split('') !")],
                region_rewrites=[])
            return ModelCall(provider="fake", model="fake", parsed=result, latency_s=0.0)

    monkeypatch.setattr(pipeline, "models", lambda: (FakeTranscriber(), CorrectingAnalyzer()))
    monkeypatch.setattr("backend.session.state.LOG_ROOT", tmp_path)
    s = Session(id="s", problem_id="two-sum", problem_text="Two Sum")

    async def emit(e):
        pass

    asyncio.run(pipeline.run_pass(s, b"img", "image/jpeg", emit))
    line = s.board_state()["regions"][0]["lines"][0]
    assert line == {"n": 1, "text": "str2 = str2.split('') !", "lowConfidenceChars": [],
                    "corrected": True, "transcribedText": "str2 = str2.split('');"}
    # Same raw transcription next pass: analyzer is skipped even though displayed text differs.
    asyncio.run(pipeline.run_pass(s, b"img", "image/jpeg", emit))
    assert len(calls) == 1


def test_region_rewrite_replaces_invented_lines():
    from backend.models.schemas import RegionRewrite
    invented = Transcription.model_validate({"regions": [{"id": "code_1", "type": "code",
        "bbox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1},
        "lines": [{"n": i, "text": t, "low_confidence_chars": []} for i, t in enumerate(
            ["def twoSum(nums, target):", "for i in range(len(nums)):", "return [i, j]"], 1)]}]})
    out, originals = pipeline.apply_corrections(invented, [], [RegionRewrite(
        region_id="code_1", lines=["def twoSum(values, target):", "seen = {}"])])
    assert [ln.text for ln in out.regions[0].lines] == ["def twoSum(values, target):", "seen = {}"]
    assert originals == {("code_1", 1): "def twoSum(nums, target):", ("code_1", 2): "for i in range(len(nums)):"}


def test_rewrite_adds_region_transcriber_missed():
    from backend.models.schemas import RegionRewrite
    out, originals = pipeline.apply_corrections(Transcription(regions=[]), [], [RegionRewrite(
        region_id="code_1", lines=["def twoSum(values, target):", "seen = []"])])
    assert [r.id for r in out.regions] == ["code_1"]
    assert out.regions[0].lines[1].text == "seen = []"


def test_board_state_sent_before_analysis_finishes(client):
    sid = client.post("/sessions", json={"problemId": "two-sum"}).json()["sessionId"]
    with client.websocket_connect(f"/sessions/{sid}/ws") as ws:
        ws.send_json({"type": "frame", "capturedAt": "t", "imageData": FRAME})
        states = []
        deadline = time.time() + 5
        while time.time() < deadline and len(states) < 2:
            ev = ws.receive_json()
            if ev["type"] == "boardState":
                states.append(ev)
    assert [s["analysisPending"] for s in states] == [True, False]
    assert states[0]["regions"] and states[1]["findings"]


def test_sync_returns_fresh_board_when_idle(client):
    sid = client.post("/sessions", json={"problemId": "two-sum"}).json()["sessionId"]
    body = client.post(f"/sessions/{sid}/sync", json={"timeoutSeconds": 0.5}).json()
    assert body["fresh"] is True and body["boardState"]["type"] == "boardState"


def test_sync_times_out_while_change_is_pending(client):
    sid = client.post("/sessions", json={"problemId": "two-sum"}).json()["sessionId"]
    app_module.store.get(sid).pending_change = True
    start = time.time()
    body = client.post(f"/sessions/{sid}/sync", json={"timeoutSeconds": 0.3}).json()
    assert body["fresh"] is False and time.time() - start >= 0.3


def test_voice_endpoints(client):
    sid = client.post("/sessions", json={"problemId": "two-sum"}).json()["sessionId"]
    cfg = client.get(f"/sessions/{sid}/voice-config").json()
    assert cfg["voiceName"] == app_module.config.VOICE_NAME
    assert "Two Sum" in cfg["systemPrompt"] and {t["name"] for t in cfg["tools"]} == {
        "ask_question", "point_to_region", "flag_error_type", "give_hint"}
    assert client.post(f"/sessions/{sid}/interjection").json() == {"release": None}
    assert client.post(f"/sessions/{sid}/phase", json={"phase": "tracing"}).json()["ok"]
    assert client.post(f"/sessions/{sid}/phase", json={"phase": "nap"}).status_code == 422
    assert client.post(f"/sessions/{sid}/tools", json={"name": "give_hint", "args": {"level": 1}}).json()["ok"]
    assert client.post(f"/sessions/{sid}/transcript", json={"role": "candidate", "text": "hi"}).json()["ok"]


def test_submit_keeps_board_snapshot_and_allows_resubmit(client):
    sid = client.post("/sessions", json={"problemId": "two-sum"}).json()["sessionId"]
    session = app_module.store.get(sid)
    session.apply_pass(T, [])
    first = client.post(f"/sessions/{sid}/submit", json={"code": "a = 1", "language": "js"}).json()
    assert first["boardSnapshot"] == ["str2 = str2.split('');"] and first["typedCode"] == ["a = 1"]
    # The board changes after submit; the snapshot does not, and typed code can be resubmitted.
    session.apply_pass(Transcription.model_validate({"regions": []}), [])
    second = client.post(f"/sessions/{sid}/submit", json={"code": "str2 = str2.split('');"}).json()
    assert second["boardSnapshot"] == first["boardSnapshot"]
    assert second["changedAfterBoard"] is False
    assert client.get(f"/sessions/{sid}/submission").json()["typedCode"] == ["str2 = str2.split('');"]
    assert session.phase == "done"
