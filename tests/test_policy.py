from backend.models.schemas import Finding
from backend.policy import ConversationState, candidate_signals_done, decide
from backend.session.state import TrackedFinding


def tf(tier, conf=0.9, status="new", line=1, fid="f1", seen=1):
    return TrackedFinding(id=fid, status=status, first_seen_pass=seen, finding=Finding(
        tier=tier, category="c", line=line, region_id="code_1", confidence=conf, message="m"))


def state(**kw):
    return ConversationState(now=100.0, **kw)


def test_tier4_never_released():
    assert decide([tf(4)], state(candidate_done_or_tracing=True)) is None


def test_highest_tier_first():
    r = decide([tf(2, fid="a"), tf(1, fid="b"), tf(3, fid="c")], state(candidate_done_or_tracing=True))
    assert r.finding.id == "b"


def test_tier3_waits_for_done_or_trace():
    assert decide([tf(3)], state()) is None
    assert decide([tf(3)], state(candidate_done_or_tracing=True)).finding.id == "f1"


def test_low_confidence_becomes_question():
    assert decide([tf(2, conf=0.55)], state()).mode == "question"
    assert decide([tf(2, conf=0.6)], state()).mode == "correction"


def test_cooldown_and_speaking_block_release():
    assert decide([tf(2)], state(last_release_at=90.0)) is None
    assert decide([tf(2)], state(last_release_at=70.0)) is not None
    assert decide([tf(2)], state(last_candidate_speech_at=99.5)) is None


def test_released_or_resolved_not_repeated():
    assert decide([tf(2, status="released"), tf(2, status="resolved", fid="g")], state()) is None


def test_done_detection():
    assert candidate_signals_done("Okay I think that's it")
    assert candidate_signals_done("let's trace through with the first example")
    assert not candidate_signals_done("so I'll use a hash map here")


def test_no_release_while_interviewer_speaking():
    assert decide([tf(1)], state(interviewer_speaking=True)) is None


def test_check_request_detection_and_cooldown_bypass():
    from backend.policy import candidate_asks_for_check
    assert candidate_asks_for_check("does everything look okay so far?")
    assert candidate_asks_for_check("Is this right?")
    assert not candidate_asks_for_check("I'll loop over the values")
    assert decide([tf(2)], state(last_release_at=95.0)) is None
    assert decide([tf(2)], state(last_release_at=95.0, candidate_asked_for_check=True)) is not None


def test_addressed_vs_thinking_aloud():
    from backend.policy import addressed_to_interviewer
    assert addressed_to_interviewer("Can the list have negative numbers?")
    assert addressed_to_interviewer("Yeah I'm ready")
    assert addressed_to_interviewer("could I get a hint")
    assert not addressed_to_interviewer("so I'll keep a map from value to index and then check the complement")
    assert not addressed_to_interviewer("okay so here we loop over the values")
