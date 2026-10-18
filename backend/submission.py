"""Code submission: the typed code takes priority, and a line diff records how it
differs from the whiteboard.

The board and the editor are never synced. The first submit takes a snapshot of the board
(`board_snapshot`), which no longer changes. The typed code (`typed_code`) stays editable:
every later submit replaces it and recomputes the diff. Each line is labeled:
same, formatting (whitespace only), changed, added (typed only), removed (board only).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from backend.models.schemas import Transcription

Op = Literal["same", "formatting", "changed", "added", "removed"]


def board_code_lines(t: Transcription | None) -> list[str]:
    """Code regions in reading order (region ids are already numbered that way)."""
    if t is None:
        return []
    code = sorted((r for r in t.regions if r.type == "code"), key=lambda r: (r.bbox.y1, r.bbox.x1))
    return [ln.text for r in code for ln in r.lines]


def _norm(line: str) -> str:
    return " ".join(line.split())


@dataclass
class DiffLine:
    op: Op
    board_line: int | None  # 1-based index into board_snapshot, None for added lines
    typed_line: int | None  # 1-based index into typed_code, None for removed lines
    board_text: str | None
    typed_text: str | None

    def as_json(self) -> dict[str, Any]:
        return {"op": self.op, "boardLine": self.board_line, "typedLine": self.typed_line,
                "boardText": self.board_text, "typedText": self.typed_text}


def line_diff(board: list[str], typed: list[str]) -> list[DiffLine]:
    """Align on whitespace-normalized lines so re-indenting is not counted as a change."""
    out: list[DiffLine] = []
    matcher = difflib.SequenceMatcher(a=[_norm(x) for x in board], b=[_norm(x) for x in typed],
                                      autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                op: Op = "same" if board[i] == typed[j] else "formatting"
                out.append(DiffLine(op, i + 1, j + 1, board[i], typed[j]))
            continue
        # replace / delete / insert: pair lines up in order, leftovers are removed or added.
        pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        for k in range(pairs):
            out.append(DiffLine("changed", i1 + k + 1, j1 + k + 1, board[i1 + k], typed[j1 + k]))
        for i in range(i1 + pairs, i2):
            out.append(DiffLine("removed", i + 1, None, board[i], None))
        for j in range(j1 + pairs, j2):
            out.append(DiffLine("added", None, j + 1, None, typed[j]))
    return out


@dataclass
class Submission:
    board_snapshot: list[str]
    typed_code: list[str]  # takes priority over the board; replaced on every resubmit
    diff: list[DiffLine] = field(default_factory=list)
    language: str | None = None
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def counts(self) -> dict[str, int]:
        counts = {op: 0 for op in ("same", "formatting", "changed", "added", "removed")}
        for d in self.diff:
            counts[d.op] += 1
        return counts

    def as_json(self) -> dict[str, Any]:
        return {"type": "submission", "submittedAt": self.submitted_at, "language": self.language,
                "boardSnapshot": self.board_snapshot, "typedCode": self.typed_code,
                "diff": [d.as_json() for d in self.diff], "counts": self.counts,
                # True when the typed code changed anything beyond whitespace.
                "changedAfterBoard": any(d.op in ("changed", "added", "removed") for d in self.diff)}


def submit(transcription: Transcription | None, typed_code: str, language: str | None) -> Submission:
    board = board_code_lines(transcription)
    typed = typed_code.replace("\r\n", "\n").rstrip("\n").split("\n") if typed_code.strip() else []
    return Submission(board_snapshot=board, typed_code=typed, diff=line_diff(board, typed),
                      language=language)
