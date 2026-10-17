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
