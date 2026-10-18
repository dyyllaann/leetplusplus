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
            tier=2, category="logic", line=1, region_id="code_1", confidence=0.9, message="m")])
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
            if ev["type"] == "boardState":
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
