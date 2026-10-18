"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { boardCodeText, submitCode } from "@/lib/api";
import type { BoardState, Submission } from "@/lib/types";
import { DiffView } from "@/app/_components/session/DiffView";

const LANGUAGES = ["python", "javascript", "typescript", "java", "cpp"] as const;
const INDENT = "    ";

function load(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable (private window); the draft just won't persist.
  }
}

/**
 * Typed code, separate from the whiteboard transcript. It only receives board text when the
 * user clicks "Copy from board"; the camera never changes it. Submitting sends the typed code
 * (which takes priority) and shows a line diff against the board snapshot. The code stays
 * editable and can be resubmitted.
 */
export function EditorTab({
  sessionId,
  problemId,
  board,
  submission,
  onSubmitted,
}: {
  sessionId: string | null;
  problemId: string;
  board: BoardState | null;
  /** Latest submission, e.g. from useSessionEvents; falls back to this tab's own result. */
  submission?: Submission | null;
  onSubmitted?: (submission: Submission) => void;
}) {
  const draftKey = `leetplusplus:editor:${problemId}`;
  const langKey = `leetplusplus:editor-lang:${problemId}`;
  const [code, setCode] = useState("");
  const [language, setLanguage] = useState<string>("python");
  const [view, setView] = useState<"edit" | "diff">("edit");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ownSubmission, setOwnSubmission] = useState<Submission | null>(null);
  const gutterRef = useRef<HTMLDivElement | null>(null);
  const latest = submission ?? ownSubmission;

  useEffect(() => {
    setCode(load(draftKey) ?? "");
    setLanguage(load(langKey) ?? "python");
  }, [draftKey, langKey]);

  function update(next: string) {
    setCode(next);
    save(draftKey, next);
  }

  function copyFromBoard() {
    const text = boardCodeText(board);
    if (!text) return;
    if (code.trim() && !window.confirm("Replace the code in the editor with the current board transcript?")) return;
    update(text);
    setView("edit");
  }

  async function submit() {
    if (!sessionId || !code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await submitCode(sessionId, code, language);
      setOwnSubmission(result);
      onSubmitted?.(result);
      setView("diff");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Tab" || event.shiftKey) return;
    event.preventDefault();
    const el = event.currentTarget;
    const { selectionStart: start, selectionEnd: end } = el;
    update(code.slice(0, start) + INDENT + code.slice(end));
    requestAnimationFrame(() => el.setSelectionRange(start + INDENT.length, start + INDENT.length));
  }

  const lineCount = Math.max(code.split("\n").length, 1);
  const editedSinceSubmit = !!latest && latest.typedCode.join("\n") !== code.replace(/\n+$/, "");
  const hasBoardCode = !!boardCodeText(board);

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Code editor">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-stone-200 px-3 py-2">
        <div className="flex items-center gap-1" role="group" aria-label="Editor view">
          {(["edit", "diff"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              disabled={v === "diff" && !latest}
              onClick={() => setView(v)}
              className={`rounded px-2 py-1 text-xs font-semibold disabled:opacity-40 ${
                view === v ? "bg-stone-200 text-stone-800" : "text-stone-500 enabled:hover:bg-stone-100"
              }`}
            >
              {v === "edit" ? "Edit" : "Diff vs board"}
            </button>
          ))}
        </div>
        <label className="ml-auto flex items-center gap-1 text-xs text-stone-500">
          <span className="sr-only">Language</span>
          <select
            value={language}
            onChange={(e) => {
              setLanguage(e.target.value);
              save(langKey, e.target.value);
            }}
            className="rounded border border-stone-300 bg-transparent px-1 py-1 text-xs text-stone-700"
          >
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>
                {l === "cpp" ? "C++" : l[0].toUpperCase() + l.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={copyFromBoard}
          disabled={!hasBoardCode}
          title={hasBoardCode ? "Copy the board transcript into the editor once" : "No code on the board yet"}
          className="rounded border border-stone-300 px-2 py-1 text-xs font-medium text-stone-700 enabled:hover:bg-stone-100 disabled:opacity-50"
        >
          Copy from board
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={!sessionId || !code.trim() || busy}
          title={sessionId ? undefined : "Start a session to submit"}
          className="rounded bg-emerald-700 px-3 py-1 text-xs font-semibold text-white enabled:hover:bg-emerald-800 disabled:opacity-50"
        >
          {busy ? "Submitting…" : latest ? "Resubmit" : "Submit"}
        </button>
      </div>

      {error && <p className="border-b border-stone-200 px-3 py-2 text-xs text-red-700">Submit failed: {error}</p>}
      {latest && editedSinceSubmit && view === "edit" && (
        <p className="border-b border-stone-200 px-3 py-1.5 text-xs text-stone-500">Edited since last submit.</p>
      )}

      {view === "diff" && latest ? (
        <DiffView submission={latest} />
      ) : (
        <div className="relative flex min-h-0 flex-1 bg-[#fbfcfa] font-mono text-sm leading-6">
          <div
            ref={gutterRef}
            aria-hidden
            className="w-10 shrink-0 select-none overflow-hidden py-3 pr-2 text-right text-stone-400"
          >
            {Array.from({ length: lineCount }, (_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>
          <textarea
            aria-label="Typed code"
            value={code}
            onChange={(e) => update(e.target.value)}
            onKeyDown={onKeyDown}
            onScroll={(e) => {
              if (gutterRef.current) gutterRef.current.scrollTop = e.currentTarget.scrollTop;
            }}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            wrap="off"
            placeholder={hasBoardCode ? "Type your solution, or use Copy from board…" : "Type your solution…"}
            className="min-h-0 flex-1 resize-none bg-transparent py-3 pr-3 text-stone-800 outline-none placeholder:font-sans placeholder:text-stone-400"
          />
        </div>
      )}
    </section>
  );
}
