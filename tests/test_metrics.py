import asyncio
import time

from backend import metrics
from backend.session.state import Session
from backend.voice.brain import BrainDecision

from tests.test_app import FRAME, client  # noqa: F401  (fixture)


def test_record_appends_and_summarize_reports_percentiles(tmp_path):
    for s in (1.0, 2.0, 3.0, 10.0):
        metrics.record(tmp_path, "analyze_written", s, pass_n=1)
    metrics.record(tmp_path, "audio_response", 0.5)
    entries = metrics.load(tmp_path)
    assert len(entries) == 5 and entries[0]["pass_n"] == 1
    summary = metrics.summarize(entries)
    assert summary["analyze_written"] == {"count": 4, "mean": 4.0, "p50": 3.0, "p90": 10.0, "max": 10.0}
    assert summary["audio_response"]["count"] == 1


def test_load_without_file_is_empty(tmp_path):
    assert metrics.load(tmp_path) == []
    assert metrics.summarize([]) == {}


def test_frame_pass_records_board_and_analysis_metrics(client):  # noqa: F811
    sid = client.post("/sessions", json={"problemId": "two-sum"}).json()["sessionId"]
    with client.websocket_connect(f"/sessions/{sid}/ws") as ws:
        ws.send_json({"type": "frame", "imageData": FRAME})
        deadline = time.time() + 5
        while time.time() < deadline:
            ev = ws.receive_json()
            if ev["type"] == "boardState" and not ev["analysisPending"]:
                break
    body = client.get(f"/sessions/{sid}/metrics").json()
    names = [e["metric"] for e in body["entries"]]
    assert names == ["board_to_display", "analyze_written"]
    board = body["entries"][0]
    assert board["mode"] == "full" and board["seconds"] >= board["transcribe_s"]
    assert body["summary"]["analyze_written"]["count"] == 1


class FakeBrain:
    def __init__(self, session):
        pass

    async def decide(self, event, detail="", hint=None):
        await asyncio.sleep(0.05)
        return BrainDecision(say="What happens on line 1?", point_region_id="", point_line=0,
                             flag_category="", used_hint_level=0)


class FakeLive:
    async def send_client_content(self, **kwargs):
        pass


class FakeWs:
    async def send_text(self, text):
        pass


def test_bridge_records_verbal_analysis_and_audio_response(monkeypatch, tmp_path):
    from backend.voice import bridge as bridge_module

    monkeypatch.setattr("backend.session.state.LOG_ROOT", tmp_path)
    monkeypatch.setattr(bridge_module, "InterviewerBrain", FakeBrain)
    s = Session(id="s", problem_id="two-sum", problem_text="Two Sum")
    b = bridge_module.VoiceBridge(s, FakeWs(), notify_board=None)
    b.live = FakeLive()

    async def scenario():
        b.last_candidate_speech_at = time.monotonic()
        b.candidate_buffer = "I loop over the array"
        await b._finish_utterance()
        await b._run_brain("candidate_spoke", "")
        b._record_reply_audio()  # first voiced audio chunk arrives

    asyncio.run(scenario())
    entries = {e["metric"]: e for e in metrics.load(s.log_dir)}
    assert entries["analyze_verbal"]["spoke"] is True
    audio = entries["audio_response"]
    assert audio["trigger"] == "candidate_spoke"
    assert audio["seconds"] >= audio["brain_s"] >= 0.05
    b._record_reply_audio()  # later chunks of the same line are not counted again
    assert len(metrics.load(s.log_dir)) == 2
