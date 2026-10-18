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
      {submission.review ? (
        <section className="shrink-0 border-b border-stone-200 bg-white px-3 py-3" aria-label="Code review">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h3 className="text-xs font-semibold text-stone-800">Code review</h3>
            <span className="text-[11px] text-stone-400">
              {submission.reviewModel ?? submission.reviewProvider}
              {submission.reviewLatencyS !== null && ` · ${submission.reviewLatencyS.toFixed(1)}s`}
            </span>
          </div>
          <p className="mt-1 text-sm leading-5 text-stone-700">{submission.review.summary}</p>
          {submission.review.findings.length > 0 ? (
            <ul className="mt-2 space-y-2">
              {submission.review.findings.map((finding, index) => (
                <li key={`${finding.line}-${finding.category}-${index}`} className="border-l-2 border-amber-500 pl-2 text-xs leading-5 text-stone-700">
                  <span className="font-semibold">{finding.line > 0 ? `Line ${finding.line}` : "Overall"} · Tier {finding.tier} · {finding.category}:</span>{" "}
                  {finding.message}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs font-medium text-emerald-800">No issues found.</p>
          )}
        </section>
      ) : submission.reviewError ? (
        <p className="shrink-0 border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Code was submitted, but review failed: {submission.reviewError}
        </p>
      ) : null}
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
