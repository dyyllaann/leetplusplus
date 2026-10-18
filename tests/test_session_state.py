from backend.models.schemas import Finding, Transcription
from backend.session.state import Session

T = Transcription.model_validate({"regions": [{
    "id": "code_1", "type": "code", "bbox": {"x1": 100, "y1": 200, "x2": 600, "y2": 800},
    "lines": [{"n": 1, "text": "x = 1", "low_confidence_chars": []}]}]})


def f(line, tier=2, category="logic"):
    return Finding(tier=tier, category=category, line=line, region_id="code_1",
                   confidence=0.9, message="m")


def test_persistent_finding_keeps_id_and_status():
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(T, [f(4, category="wrong method")])
    s.findings[0].status = "released"
    s.apply_pass(T, [f(4, category="runtime error")])
    assert len(s.findings) == 1
    assert s.findings[0].id == "f1" and s.findings[0].status == "released"


def test_missing_finding_is_resolved_and_new_one_added():
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(T, [f(4)])
    s.apply_pass(T, [f(5)])
    assert [(t.id, t.status) for t in s.findings] == [("f1", "resolved"), ("f2", "new")]


def test_board_state_normalizes_bbox_and_uses_camel_case():
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(T, [f(1)])
    state = s.board_state()
    assert state["pass"] == 1
    assert state["regions"][0]["bbox"] == {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.6}
    assert state["regions"][0]["lines"][0]["lowConfidenceChars"] == []
    assert state["findings"][0]["regionId"] == "code_1" and state["findings"][0]["severity"] == 2


def test_transcription_published_before_analysis_keeps_old_findings():
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(T, [f(1)])
    s.apply_transcription(T)
    state = s.board_state()
    assert state["analysisPending"] is True
    assert state["pass"] == 1 and state["findings"][0]["id"] == "f1"
    s.apply_pass(T, [f(1)])
    assert s.board_state()["analysisPending"] is False


def test_is_current_requires_no_transcription_in_flight_and_no_pending_change():
    s = Session(id="s", problem_id="p", problem_text="")
    assert s.is_current()
    s.pending_change = True
    assert not s.is_current()
    s.pending_change, s.transcribing = False, True
    assert not s.is_current()
