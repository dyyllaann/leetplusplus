import asyncio

from backend.models.schemas import Finding, Transcription
from backend.policy import Release
from backend.session.state import Session, TrackedFinding
from backend.voice.bridge import coach_detail
from backend.voice.brain import render_request
from backend.voice.tools import FUNCTION_DECLARATIONS, HintLadder, VoiceTools

T = Transcription.model_validate({"regions": [{
    "id": "code_1", "type": "code", "bbox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1},
    "lines": [{"n": 1, "text": "comp != target - n", "low_confidence_chars": []}]}]})


def session_with_finding(tier=2, conf=0.9):
    s = Session(id="s", problem_id="two-sum", problem_text="Two Sum")
    s.apply_pass(T, [Finding(tier=tier, category="missing_state_update", line=1, region_id="code_1",
                             confidence=conf, message="SECRET FIX: use = not !=")])
    return s


def test_only_allowed_tools_are_declared():
    assert {d["name"] for d in FUNCTION_DECLARATIONS} == {
        "ask_question", "point_to_region", "flag_error_type", "give_hint"}


def test_hint_ladder_enforces_levels():
    h = HintLadder()
    assert h.allowed(1, 0) and not h.allowed(2, 0)
    h.give(1, 0)
    assert not h.allowed(2, 30)
    assert h.allowed(2, 91)          # unlocked by time
    h.requested = True
    assert h.allowed(2, 31)          # unlocked by explicit request
    assert not h.allowed(3, 31)      # never skip a level
    assert not h.allowed(4, 1000)


def test_give_hint_tool_uses_backend_findings_and_never_the_fix():
    s = session_with_finding()
    events = []

    async def emit(e):
        events.append(e)

    tools = VoiceTools(s, emit, clock=lambda: 0.0)
    r1 = asyncio.run(tools.call("give_hint", {"level": 1}))
    r2 = asyncio.run(tools.call("give_hint", {"level": 2}))
    assert "line 1" in r1["hint"]
    assert r2 == {"hint": "not yet available"}
    assert all("SECRET" not in str(c["result"]) for c in s.tool_calls)


def test_point_and_flag_emit_highlight_and_validate_category():
    s = session_with_finding()
    events = []

    async def emit(e):
        events.append(e)

    tools = VoiceTools(s, emit, clock=lambda: 0.0)
    asyncio.run(tools.call("point_to_region", {"region_id": "code_1", "line": 1}))
    bad = asyncio.run(tools.call("flag_error_type", {"region_id": "code_1", "line": 1, "category": "write code"}))
    assert events == [{"type": "highlight", "regionId": "code_1", "line": 1}]
    assert "error" in bad


def test_brain_request_has_board_and_hint_but_no_finding_messages():
    s = session_with_finding()
    s.transcript.append({"role": "candidate", "text": "does this look okay?"})
    req = render_request(s, "candidate_spoke", "", (1, "Ask them to trace line 1."))
    assert "line 1: comp != target - n" in req
    assert "candidate: does this look okay?" in req
    assert "level 1: Ask them to trace line 1." in req
    assert "SECRET" not in req


def test_coach_detail_modes_omit_the_fix():
    s = session_with_finding(conf=0.5)
    tf: TrackedFinding = s.findings[0]
    assert "probing question" in coach_detail(Release(tf, "question"))
    correction = coach_detail(Release(tf, "correction"))
    assert "line=1" in correction and "missing_state_update" in correction
    assert "SECRET" not in correction


def test_bridge_only_voices_brain_lines(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    from backend.voice.bridge import VoiceBridge
    b = VoiceBridge(session_with_finding(), ws=None, notify_board=None)
    assert not b.should_voice_turn()      # Gemini replying on its own: muted
    b.awaiting_response = True            # a [SAY] from the brain: played
    assert b.should_voice_turn()
