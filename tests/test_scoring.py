import json
from pathlib import Path

from backend.evaluation.scoring import char_accuracy, score_findings, score_transcription
from backend.models.schemas import Finding, Transcription

EXPECTED = json.loads((Path(__file__).parents[1] / "fixtures/whiteboard_1.expected.json").read_text())
EXPECTED_LINES = EXPECTED["regions"][0]["lines"]


def make_transcription(lines):
    return Transcription.model_validate({"regions": [{
        "id": "code_1", "type": "code", "bbox": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
        "lines": [{"n": i, "text": t, "low_confidence_chars": []} for i, t in enumerate(lines, 1)],
    }]})


def finding(tier, line, message, category="logic"):
    return Finding(tier=tier, category=category, line=line, region_id="code_1",
                   confidence=0.9, message=message)


def test_char_accuracy_ignores_whitespace():
    assert char_accuracy("return str===str2;", "return str === str2 ;") == 1.0
    assert char_accuracy("abcd", "abce") == 0.75
    assert char_accuracy("ab", "xxxxxx") == 0.0


def test_exact_transcription_preserves_errors():
    s = score_transcription(make_transcription(EXPECTED_LINES), EXPECTED)
    assert s.char_accuracy == 1.0
    assert s.missing == [] and s.fixed == []
    assert not s.failed


def test_corrected_transcription_fails():
    lines = list(EXPECTED_LINES)
    lines[3] = "str2 = str2.join('');"
    s = score_transcription(make_transcription(lines), EXPECTED)
    assert "P1" in s.fixed and "P1" in s.missing
    assert s.failed


def test_finds_known_error_with_correct_tier():
    s = score_findings([finding(2, 4, "Arrays have no split method; this should rebuild a string.")], EXPECTED)
    assert s.recall == 1.0 and s.tier_correct == ["E1"]
    assert not s.fp_serious


def test_known_error_at_wrong_tier_counts_recall_not_tier():
    s = score_findings([finding(4, 4, "split called on array")], EXPECTED)
    assert s.recall == 1.0 and s.tier_correct == []


def test_tier1_is_false_positive_when_approach_is_correct():
    s = score_findings([finding(1, 4, "Reverse-and-compare will not work; split is wrong")], EXPECTED)
    assert s.recall == 0.0
    assert len(s.fp_serious) == 1


def test_acceptable_and_unmatched_findings():
    s = score_findings([
        finding(2, 5, "Compares a string to an array, so always false."),
        finding(3, 0, "What about uppercase letters?", category="edge case"),
        finding(2, 2, "Variable naming is unclear."),
        finding(4, 1, "Missing semicolon after brace."),
    ], EXPECTED)
    assert s.acceptable_found == ["A1", "A2"]
    assert len(s.fp_serious) == 1 and len(s.fp_minor) == 1
