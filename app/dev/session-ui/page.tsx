"use client";

// Dev-only preview of the new session components with mock data (no backend needed).
// Open /dev/session-ui. Safe to delete once the components are wired into the problem page.

import { useState } from "react";
import { DiffView } from "@/app/_components/session/DiffView";
import { EditorTab } from "@/app/_components/session/EditorTab";
import { HighlightOverlay, isHighlightedLine } from "@/app/_components/session/HighlightOverlay";
import type { BoardState, HighlightEvent, Submission } from "@/lib/types";

const BOARD: BoardState = {
  type: "boardState",
  pass: 3,
  updatedAt: null,
  analysisPending: false,
  findings: [],
  regions: [
    {
      id: "code_1",
      type: "code",
      bbox: { x: 0.08, y: 0.12, width: 0.5, height: 0.6 },
      lines: [
        "def has_pair(nums, target):",
        "    seen = set()",
        "    for n in nums:",
        "        if target - n in seen:",
        "            return True",
        "        seen.add(n)",
        "    return False",
      ].map((text, i) => ({ n: i + 1, text, lowConfidenceChars: [], corrected: false })),
    },
    {
      id: "examples_1",
      type: "examples",
      bbox: { x: 0.64, y: 0.12, width: 0.28, height: 0.2 },
      lines: [{ n: 1, text: "[1,2,4,4], 8 -> True", lowConfidenceChars: [], corrected: false }],
    },
  ],
};

const SUBMISSION: Submission = {
  type: "submission",
  submittedAt: new Date().toISOString(),
  language: "python",
  boardSnapshot: ["def has_pair(nums, target):", "  seen = set()", "  for n in nums:", "    if target - n in seen:", "      return True", "  return None"],
  typedCode: ["def has_pair(nums, target):", "    seen = set()", "    for n in nums:", "        if target - n in seen:", "            return True", "        seen.add(n)", "    return False"],
  diff: [
    { op: "same", boardLine: 1, typedLine: 1, boardText: "def has_pair(nums, target):", typedText: "def has_pair(nums, target):" },
    { op: "formatting", boardLine: 2, typedLine: 2, boardText: "  seen = set()", typedText: "    seen = set()" },
    { op: "formatting", boardLine: 3, typedLine: 3, boardText: "  for n in nums:", typedText: "    for n in nums:" },
    { op: "formatting", boardLine: 4, typedLine: 4, boardText: "    if target - n in seen:", typedText: "        if target - n in seen:" },
    { op: "formatting", boardLine: 5, typedLine: 5, boardText: "      return True", typedText: "            return True" },
    { op: "added", boardLine: null, typedLine: 6, boardText: null, typedText: "        seen.add(n)" },
    { op: "changed", boardLine: 6, typedLine: 7, boardText: "  return None", typedText: "    return False" },
  ],
  counts: { same: 1, formatting: 4, changed: 1, added: 1, removed: 0 },
  changedAfterBoard: true,
};

export default function SessionUiPreview() {
  const [highlight, setHighlight] = useState<HighlightEvent | null>({ type: "highlight", regionId: "code_1", line: 4 });
  const region = BOARD.regions[0];
  return (
    <main className="grid min-h-screen gap-4 bg-[#f7f8f5] p-4 lg:grid-cols-2">
      <section className="flex flex-col gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-stone-600">Highlight overlay</h2>
        <div className="relative aspect-video w-full border border-stone-300 bg-[#dde2dc]">
          {BOARD.regions.map((r) => (
            <div
              key={r.id}
              className="absolute border-2 border-emerald-500"
              style={{ left: `${r.bbox.x * 100}%`, top: `${r.bbox.y * 100}%`, width: `${r.bbox.width * 100}%`, height: `${r.bbox.height * 100}%` }}
            />
          ))}
          <HighlightOverlay regions={BOARD.regions} highlight={highlight} />
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          {[0, 1, 4, 7].map((line) => (
            <button key={line} type="button" className="rounded border border-stone-300 px-2 py-1" onClick={() => setHighlight({ type: "highlight", regionId: "code_1", line })}>
              {line ? `Line ${line}` : "Whole region"}
            </button>
          ))}
          <button type="button" className="rounded border border-stone-300 px-2 py-1" onClick={() => setHighlight(null)}>
            Clear
          </button>
        </div>
        <div className="border border-stone-200 bg-[#fbfcfa] p-3 font-mono text-sm leading-6">
          {region.lines.map((l) => (
            <div key={l.n} className={`flex gap-3 ${isHighlightedLine(highlight, region.id, l.n) ? "bg-amber-300/30" : ""}`}>
              <span className="w-6 text-right text-stone-400">{l.n}</span>
              <span className="whitespace-pre">{l.text}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="flex min-h-[420px] flex-col border border-stone-200">
        <h2 className="border-b border-stone-200 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-stone-600">Editor tab</h2>
        <EditorTab sessionId={null} problemId="dev-preview" board={BOARD} />
      </section>
      <section className="flex min-h-[320px] flex-col border border-stone-200 lg:col-span-2">
        <h2 className="border-b border-stone-200 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-stone-600">Diff view</h2>
        <DiffView submission={SUBMISSION} />
      </section>
    </main>
  );
}
