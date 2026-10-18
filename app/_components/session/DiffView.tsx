"use client";

import type { DiffLine, DiffOp, Submission } from "@/lib/types";

const OP_STYLE: Record<DiffOp, { row: string; mark: string; label: string }> = {
  same: { row: "", mark: " ", label: "Unchanged" },
  formatting: { row: "", mark: "~", label: "Whitespace only" },
  changed: { row: "bg-amber-400/15", mark: "±", label: "Changed after the board" },
  added: { row: "bg-emerald-500/15", mark: "+", label: "Added after the board" },
  removed: { row: "bg-red-500/15", mark: "−", label: "On the board, removed when typed" },
};

function Row({ d }: { d: DiffLine }) {
  const style = OP_STYLE[d.op];
  return (
    <div className={`grid grid-cols-[2rem_1rem_1fr] gap-2 px-3 ${style.row}`} title={style.label}>
      <span className="select-none text-right text-stone-400">{d.typedLine ?? d.boardLine ?? ""}</span>
      <span className="select-none text-stone-500" aria-label={style.label}>
        {style.mark}
      </span>
      <span className="whitespace-pre-wrap">
        {d.op === "changed" ? (
          <>
            <span className="block text-stone-500 line-through decoration-red-500/60">{d.boardText}</span>
            <span className="block">{d.typedText}</span>
          </>
        ) : d.op === "removed" ? (
          <span className="text-stone-500 line-through decoration-red-500/60">{d.boardText}</span>
        ) : (
          d.typedText
        )}
      </span>
    </div>
  );
}

/** Line diff between the board snapshot and the typed code (typed code takes priority). */
export function DiffView({ submission }: { submission: Submission }) {
  const { counts } = submission;
  const edits = counts.changed + counts.added + counts.removed;
  return (
    <div className="flex min-h-0 flex-col">
      <p className="border-b border-stone-200 px-3 py-2 text-xs text-stone-500">
        {edits === 0
          ? "Typed code matches the whiteboard."
          : `${edits} line${edits === 1 ? "" : "s"} differ from the whiteboard: ${counts.changed} changed, ${counts.added} added, ${counts.removed} removed.`}
        {counts.formatting > 0 && ` ${counts.formatting} whitespace-only.`}
      </p>
      <div className="min-h-0 flex-1 overflow-y-auto py-2 font-mono text-sm leading-6 text-stone-800">
        {submission.diff.length === 0 ? (
          <p className="px-3 font-sans text-stone-400">Nothing to compare yet.</p>
        ) : (
          submission.diff.map((d, i) => <Row key={i} d={d} />)
        )}
      </div>
    </div>
  );
}
