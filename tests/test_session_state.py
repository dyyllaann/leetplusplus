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


def board(*lines):
    return Transcription.model_validate({"regions": [{
        "id": "code_1", "type": "code", "bbox": {"x1": 0, "y1": 0, "x2": 500, "y2": 500},
        "lines": [{"n": i, "text": t, "low_confidence_chars": []} for i, t in enumerate(lines, 1)]}]})


def test_finding_follows_its_line_when_a_line_is_inserted_above():
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(board("def f(a):", "for x in a:", "if x < 0:"), [f(3)])
    s.findings[0].status = "released"
    s.apply_pass(board("def f(a):", "seen = set()", "for x in a:", "if x < 0:"), [f(4)])
    assert len(s.findings) == 1
    t = s.findings[0]
    assert (t.id, t.status, t.finding.line) == ("f1", "released", 4)


def test_finding_kept_when_its_line_is_edited_in_place():
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(board("a", "b", "if x < 0:"), [f(3)])
    s.findings[0].status = "released"
    s.apply_pass(board("a", "b", "if x < 0 or y:"), [f(3)])
    assert [(t.id, t.status) for t in s.findings] == [("f1", "released")]


def test_duplicate_line_text_matches_the_closest_line():
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(board("}", "x", "}"), [f(1), f(3)])
    s.findings[1].status = "released"  # the finding on line 3
    s.apply_pass(board("new", "}", "x", "}"), [f(2), f(4)])
    by_line = {t.finding.line: (t.id, t.status) for t in s.findings}
    assert by_line == {2: ("f1", "new"), 4: ("f2", "released")}


def test_fixed_line_resolves_and_a_different_line_is_new():
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(board("a", "if x < 0:"), [f(2)])
    s.apply_pass(board("a", "if x <= 0:", "return y"), [f(3)])
    assert [(t.id, t.status, t.finding.line) for t in s.findings] == [
        ("f1", "resolved", 2), ("f2", "new", 3)]


def test_new_issue_on_inserted_line_does_not_steal_the_moved_finding():
    s = Session(id="s", problem_id="p", problem_text="")
    s.apply_pass(board("a", "b", "if x < 0:"), [f(3)])
    s.findings[0].status = "released"
    # A new line 3 with its own issue is listed first; the old issue moved to line 4.
    s.apply_pass(board("a", "b", "y = z[0]", "if x < 0:"), [f(3), f(4)])
    by_line = {t.finding.line: (t.id, t.status) for t in s.findings}
    assert by_line == {3: ("f2", "new"), 4: ("f1", "released")}
