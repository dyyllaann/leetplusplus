from backend.models.schemas import Transcription
from backend.submission import board_code_lines, line_diff, submit


def board(*lines, examples=("in: [1,2]",)):
    return Transcription.model_validate({"regions": [
        {"id": "code_1", "type": "code", "bbox": {"x1": 0, "y1": 100, "x2": 500, "y2": 500},
         "lines": [{"n": i, "text": t, "low_confidence_chars": []} for i, t in enumerate(lines, 1)]},
        {"id": "examples_1", "type": "examples", "bbox": {"x1": 600, "y1": 0, "x2": 900, "y2": 90},
         "lines": [{"n": 1, "text": e, "low_confidence_chars": []} for e in examples]}]})


def ops(diff):
    return [(d.op, d.board_line, d.typed_line) for d in diff]


def test_only_code_regions_are_compared():
    assert board_code_lines(board("a", "b")) == ["a", "b"]


def test_labels_same_formatting_changed_added_removed():
    b = ["def f(a):", "  for x in a:", "    if x < 0:", "      return x", "  print(a)"]
    t = ["def f(a):", "    for x in a:", "        if x <= 0:", "            return x",
         "    return None"]
    assert ops(line_diff(b, t)) == [
        ("same", 1, 1), ("formatting", 2, 2), ("changed", 3, 3), ("formatting", 4, 4),
        ("changed", 5, 5)]
    assert ops(line_diff(["a", "b"], ["a"])) == [("same", 1, 1), ("removed", 2, None)]
    assert ops(line_diff(["a"], ["a", "c"])) == [("same", 1, 1), ("added", None, 2)]


def test_submission_json_typed_code_takes_priority():
    sub = submit(board("x = 1", "return x"), "x = 2\nreturn x\n", "python")
    j = sub.as_json()
    assert j["typedCode"] == ["x = 2", "return x"] and j["boardSnapshot"] == ["x = 1", "return x"]
    assert j["changedAfterBoard"] is True and j["counts"]["changed"] == 1


def test_whitespace_only_edits_are_not_changes():
    assert submit(board("  x=1"), "x=1", None).as_json()["changedAfterBoard"] is False
