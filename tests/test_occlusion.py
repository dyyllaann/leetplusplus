from backend.models.schemas import Transcription
from backend.vision.occlusion import only_lost_text


def t(*lines):
    return Transcription.model_validate({"regions": [{"id": "code_1", "type": "code",
        "bbox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1},
        "lines": [{"n": i, "text": x, "low_confidence_chars": []} for i, x in enumerate(lines, 1)]}]})


FULL = t("def twoSum(nums, target):", "seen = {}", "for i, n in enumerate(nums):", "comp = target - n")


def test_empty_reading_is_occlusion():
    assert only_lost_text(FULL, Transcription(regions=[]))


def test_truncated_and_missing_lines_are_occlusion():
    assert only_lost_text(FULL, t("def twoSum(", "seen = {}"))


def test_new_line_is_a_real_change():
    assert not only_lost_text(FULL, t("def twoSum(nums, target):", "seen = {}", "for i, n in enumerate(nums):",
                                      "comp = target - n", "if comp in seen:"))


def test_edited_line_with_same_length_is_a_real_change():
    assert not only_lost_text(FULL, t("def twoSum(nums, target):", "seen = []", "for i, n in enumerate(nums):",
                                      "comp = target - n"))


def test_shorter_but_new_content_is_a_real_change():
    assert not only_lost_text(FULL, t("class Solution:", "pass"))


def test_first_reading_always_applies():
    assert not only_lost_text(None, t("x = 1"))
