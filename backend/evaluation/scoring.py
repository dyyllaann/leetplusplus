"""Score transcriptions and findings against a fixture's expected.json."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.models.schemas import Finding, Transcription

LINE_TOLERANCE = 1


def strip_ws(text: str) -> str:
    return re.sub(r"\s+", "", text)


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def char_accuracy(expected: str, got: str) -> float:
    """1 - edit_distance / len(expected), floored at 0. Whitespace is ignored
    because spacing in handwriting is ambiguous."""
    exp, out = strip_ws(expected), strip_ws(got)
    if not exp:
        return 1.0 if not out else 0.0
    return max(0.0, 1.0 - levenshtein(exp, out) / len(exp))


def code_lines(transcription: Transcription) -> list[str]:
    """All code-region lines, regions ordered top-to-bottom then left-to-right."""
    regions = sorted((r for r in transcription.regions if r.type == "code"),
                     key=lambda r: (r.bbox.y1, r.bbox.x1))
    return [ln.text for r in regions for ln in sorted(r.lines, key=lambda ln: ln.n)]


@dataclass
class TranscriptionScore:
    char_accuracy: float
    preserved: list[str]
    missing: list[str]
    fixed: list[str]

    @property
    def failed(self) -> bool:
        """A transcription that corrects the candidate's code is a failure."""
        return bool(self.fixed)


def score_transcription(transcription: Transcription, expected: dict[str, Any]) -> TranscriptionScore:
    exp_lines = [ln for r in expected["regions"] if r["type"] == "code" for ln in r["lines"]]
    got_lines = code_lines(transcription)
    got_flat = strip_ws("".join(got_lines))
    preserved, missing, fixed = [], [], []
    for check in expected.get("preserve_checks", []):
        (preserved if re.search(check["must_match"], got_flat) else missing).append(check["id"])
        if re.search(check["fixed_if_match"], got_flat):
            fixed.append(check["id"])
    return TranscriptionScore(
        char_accuracy=char_accuracy("\n".join(exp_lines), "\n".join(got_lines)),
        preserved=preserved, missing=missing, fixed=fixed,
    )


def code_box_iou(transcription: Transcription, expected: dict[str, Any]) -> float | None:
    """IoU between the box around all code regions and the expected code box(es).
    None when the fixture has no code region box."""
    exp = [r["approx_bbox"] for r in expected["regions"] if r["type"] == "code" and r.get("approx_bbox")]
    got = [(r.bbox.x1, r.bbox.y1, r.bbox.x2, r.bbox.y2) for r in transcription.regions if r.type == "code"]
    if not exp:
        return None
    if not got:
        return 0.0

    def union(boxes):
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    (ax1, ay1, ax2, ay2), (bx1, by1, bx2, by2) = union(exp), union(got)
    inter = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    total = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / total if total > 0 else 0.0


def line_box_coverage(transcription: Transcription) -> float:
    """Share of code lines that came back with a usable box (line patching needs one per line)."""
    lines = [ln for r in transcription.regions if r.type == "code" for ln in r.lines]
    usable = [ln for ln in lines if ln.bbox and ln.bbox.x2 > ln.bbox.x1 and ln.bbox.y2 > ln.bbox.y1]
    return len(usable) / len(lines) if lines else 0.0


def matches(finding: Finding, target: dict[str, Any]) -> bool:
    line_ok = target["line"] == 0 or finding.line == 0 or abs(finding.line - target["line"]) <= LINE_TOLERANCE
    text = f"{finding.category} {finding.message}".lower()
    return line_ok and any(k.lower() in text for k in target["keywords_any"])


@dataclass
class FindingsScore:
    required_found: list[str]
    required_total: int
    tier_correct: list[str]
    acceptable_found: list[str]
    fp_serious: list[Finding] = field(default_factory=list)  # tier 1-2 false positives
    fp_minor: list[Finding] = field(default_factory=list)    # tier 3-4 unmatched findings

    @property
    def recall(self) -> float:
        return len(self.required_found) / self.required_total if self.required_total else 1.0


def score_findings(findings: list[Finding], expected: dict[str, Any]) -> FindingsScore:
    required = [e for e in expected["known_errors"] if e.get("required", True)]
    acceptable = expected.get("acceptable_findings", [])
    approach_ok = expected.get("approach_correct", True)
    logic_ok = expected.get("logic_correct", False)

    score = FindingsScore([], len(required), [], [])
    for f in findings:
        hit_req = next((e for e in required if matches(f, e)), None)
        hit_ok = None if hit_req else next((a for a in acceptable if matches(f, a)), None)

        # Tier 1 contradicts a correct approach; tier 2 contradicts correct logic.
        wrong_tier = (f.tier == 1 and approach_ok) or (f.tier == 2 and logic_ok)
        if hit_req and not wrong_tier:
            if hit_req["id"] not in score.required_found:
                score.required_found.append(hit_req["id"])
            if f.tier == hit_req["tier"] and hit_req["id"] not in score.tier_correct:
                score.tier_correct.append(hit_req["id"])
        elif hit_ok and not wrong_tier:
            if hit_ok["id"] not in score.acceptable_found:
                score.acceptable_found.append(hit_ok["id"])
        elif f.tier <= 2:
            score.fp_serious.append(f)
        else:
            score.fp_minor.append(f)
    return score
