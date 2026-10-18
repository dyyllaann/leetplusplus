import asyncio

import pytest

from backend import policy, voice_tools
from backend.models.schemas import Finding, Transcription
from backend.session.state import Session

T = Transcription.model_validate({"regions": [{
    "id": "code_1", "type": "code", "bbox": {"x1": 0, "y1": 0, "x2": 500, "y2": 500},
    "lines": [{"n": i, "text": f"line {i}", "low_confidence_chars": []} for i in (1, 2, 3, 4)]}]})


def f(tier, line=4, confidence=0.9, category="wrong comparison"):
    return Finding(tier=tier, category=category, line=line, region_id="code_1",
                   confidence=confidence, message="SECRET FIX: use <= instead of <")


def session(*findings, stable=True, phase="writing"):
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(T, list(findings))
    s.board_stable, s.phase = stable, phase
    return s


def test_highest_tier_first_and_message_never_leaks():
    s = session(f(2, line=4), f(1, line=0, category="wrong complexity"))
    r = policy.next_release(s, now=100)
    assert r.tier == 1 and "SECRET" not in r.instruction and "<=" not in r.instruction


def test_one_interruption_at_a_time_and_cooldown():
    s = session(f(2, line=4), f(2, line=2))
    assert policy.next_release(s, 100) is not None
    assert policy.next_release(s, 100 + policy.COOLDOWN_SECONDS + 1) is None  # first still held
    assert policy.next_release(s, 100 + policy.RELEASE_HOLD_SECONDS + 1) is not None


def test_logic_waits_for_stable_board_and_finished_analysis():
    s = session(f(2), stable=False)
    assert policy.next_release(s, 100) is None
    s.board_stable, s.analysis_pending = True, True
    assert policy.next_release(s, 100) is None
    s.analysis_pending = False
    assert policy.next_release(s, 100) is not None


def test_edge_cases_wait_for_trace_and_syntax_never_released():
    s = session(f(3), f(4, line=1))
    assert policy.next_release(s, 100) is None
    s.phase = "tracing"
    assert policy.next_release(s, 100).tier == 3
    assert policy.next_release(s, 10_000) is None  # tier 4 stays report-only
    assert [t.status for t in s.findings] == ["released", "new"]


def test_low_confidence_becomes_question():
    s = session(f(2, confidence=0.4))
    r = policy.next_release(s, 100)
    assert r.mode == "question" and "Do not say there is a problem" in r.instruction


def test_hint_ladder_unlocks_over_time_or_on_request():
    s = session(f(2))
    assert policy.give_hint(s, 3, False, 100)["allowed"] is False
    assert policy.give_hint(s, 1, False, 100)["allowed"] is True
    assert policy.give_hint(s, 2, False, 110)["allowed"] is False
    assert policy.give_hint(s, 2, True, 110)["allowed"] is True  # explicit ask: one step
    assert policy.give_hint(s, 3, False, 110 + policy.HINT_UNLOCK_SECONDS)["allowed"] is True
    assert len(s.hint_events) == 3


def test_level_3_hint_names_location_not_fix():
    s = session(f(2))
    for lvl, t in ((1, 0), (2, 1000), (3, 2000)):
        out = policy.give_hint(s, lvl, False, t)
    assert "line 4" in out["instruction"] and "SECRET" not in out["instruction"]


@pytest.mark.parametrize("text,code", [
    ("What does line 4 compare?", False),
    ("What happens when the input is empty?", False),
    ("Try `for (i = 0; i < n; i++) { sum += a[i]; }`", True),
    ("What does nums.sort() return here?", False),
    ("def f(x):\n    return x + 1", True),
])
def test_code_guard(text, code):
    assert voice_tools.looks_like_code(text) is code


def run(s, name, args):
    sent = []

    async def broadcast(e):
        sent.append(e)

    return asyncio.run(voice_tools.execute(s, name, args, broadcast, now=100)), sent


def test_tools_validate_and_broadcast_highlight():
    s = session(f(2))
    out, sent = run(s, "point_to_region", {"region_id": "code_1", "line": 4})
    assert out["ok"] and sent == [{"type": "highlight", "regionId": "code_1", "line": 4}]
    assert run(s, "point_to_region", {"region_id": "code_9"})[0]["ok"] is False
    assert run(s, "write_code", {})[0]["ok"] is False
    assert run(s, "ask_question", {"text": "x = 1; y = 2; return x"})[0]["ok"] is False
    assert run(s, "give_hint", {"level": 1})[0]["ok"] is True
