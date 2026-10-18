"use client";

import { useEffect, useState } from "react";
import { EditorTab } from "@/app/_components/session/EditorTab";
import { HighlightOverlay } from "@/app/_components/session/HighlightOverlay";
import type { useCamera } from "@/lib/capture";
import type { BoardState, GateEvent, Region, StatusEvent, Submission } from "@/lib/types";

type Camera = ReturnType<typeof useCamera>;
/** Line the voice interviewer pointed to (point_to_region / flag_error_type); 0 = whole region. */
type Highlight = { regionId: string; line: number } | null;

const STAGE_LABEL: Record<StatusEvent["stage"], string> = {
  transcribing: "Reading board…",
  analyzing: "Reviewing…",
  idle: "Up to date",
  error: "Error",
};

function Pill({ on, label }: { on: boolean; label: string }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[11px] ${
        on ? "border-emerald-700 text-emerald-700" : "border-stone-300 text-stone-400"
      }`}
    >
      {label}
    </span>
  );
}

export function CameraPanel({
  camera,
  regions,
  gate,
  status,
  error,
  sessionEnded,
  highlight = null,
}: {
  camera: Camera;
  regions: Region[];
  gate: GateEvent | null;
  status: StatusEvent | null;
  error: string | null;
  sessionEnded: boolean;
  highlight?: Highlight;
}) {
  return (
    <section className="flex min-h-0 flex-col" aria-label="Camera feed">
      <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-stone-200 px-4">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-stone-600">Camera feed</h2>
        {camera.isActive && !sessionEnded ? (
          <div className="flex items-center gap-1.5" aria-live="polite">
            <Pill on={!!gate?.changed} label="changed" />
            <Pill on={!!gate?.stable} label="stable" />
            <span className="ml-1 text-xs text-stone-500">{status ? STAGE_LABEL[status.stage] : "Waiting…"}</span>
          </div>
        ) : !sessionEnded ? (
          <span className="text-xs text-stone-400">Preview</span>
        ) : null}
      </header>
      <div className="flex min-h-0 flex-1 items-center justify-center bg-[#e9ece7] p-3">
        {sessionEnded ? (
          <div className="flex aspect-video w-full items-center justify-center text-sm font-medium text-stone-600">
            Session ended.
          </div>
        ) : (
          <div
            className="relative w-full max-h-full overflow-hidden border border-stone-300 bg-[#dde2dc]"
            style={{ aspectRatio: camera.aspectRatio }}
          >
            <video ref={camera.videoRef} autoPlay playsInline muted className="absolute inset-0 h-full w-full object-cover" />
            {!camera.isActive && (
              <div className="absolute inset-0 flex items-center justify-center text-sm font-medium text-stone-500">
                {error ? `Camera unavailable: ${error}` : "Camera starts when the session begins"}
              </div>
            )}
            {regions.map((region) => (
              <div
                key={region.id}
                className="pointer-events-none absolute border-2 border-emerald-500"
                style={{
                  left: `${region.bbox.x * 100}%`,
                  top: `${region.bbox.y * 100}%`,
                  width: `${region.bbox.width * 100}%`,
                  height: `${region.bbox.height * 100}%`,
                }}
              >
                <span className="absolute -top-5 left-0 bg-emerald-600 px-1 text-[10px] text-white">{region.id}</span>
              </div>
            ))}
            <HighlightOverlay regions={regions} highlight={highlight && { type: "highlight", ...highlight }} />
          </div>
        )}
      </div>
      {!sessionEnded && camera.isActive && error && <p className="border-t border-stone-200 px-4 py-2 text-xs text-red-700">{error}</p>}
      {!sessionEnded && status?.stage === "error" && status.detail && (
        <p className="border-t border-stone-200 px-4 py-2 text-xs text-red-700">{status.detail}</p>
      )}
    </section>
  );
}

export function BoardPanel({
  board,
  problemId,
  highlight = null,
  sessionId = null,
  submission = null,
  onSubmitted,
}: {
  board: BoardState | null;
  problemId: string;
  highlight?: Highlight;
  sessionId?: string | null;
  submission?: Submission | null;
  onSubmitted?: (submission: Submission) => void;
}) {
  const codeRegions = board?.regions.filter((region) => region.type === "code") ?? [];
  const otherRegions = board?.regions.filter((region) => region.type !== "code") ?? [];
  const [activeView, setActiveView] = useState<"transcript" | "notes" | "editor">("transcript");
  const [notes, setNotes] = useState("");
  const [notesSaved, setNotesSaved] = useState(true);
  const notesStorageKey = `leetplusplus:notes:${problemId}`;

  useEffect(() => {
    setNotes(window.localStorage.getItem(notesStorageKey) ?? "");
    setNotesSaved(true);
  }, [notesStorageKey]);

  function saveNotes() {
    window.localStorage.setItem(notesStorageKey, notes);
    setNotesSaved(true);
  }

  return (
    <section className="flex min-h-[240px] flex-col border-t border-stone-200 lg:min-h-0" aria-label="Board panels">
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-stone-200 px-4">
        <div className="flex items-center gap-1" role="group" aria-label="Board panel view">
          <button
            type="button"
            aria-pressed={activeView === "transcript"}
            onClick={() => setActiveView("transcript")}
            className={`rounded px-2 py-1 text-xs font-semibold ${activeView === "transcript" ? "bg-stone-200 text-stone-800" : "text-stone-500 hover:bg-stone-100"}`}
          >
            Board Transcript
          </button>
          <button
            type="button"
            aria-pressed={activeView === "notes"}
            onClick={() => setActiveView("notes")}
            className={`rounded px-2 py-1 text-xs font-semibold ${activeView === "notes" ? "bg-stone-200 text-stone-800" : "text-stone-500 hover:bg-stone-100"}`}
          >
            Notes
          </button>
          <button
            type="button"
            aria-pressed={activeView === "editor"}
            onClick={() => setActiveView("editor")}
            className={`rounded px-2 py-1 text-xs font-semibold ${activeView === "editor" ? "bg-stone-200 text-stone-800" : "text-stone-500 hover:bg-stone-100"}`}
          >
            Editor
          </button>
        </div>
        {activeView === "editor" ? (
          <span className="text-xs text-stone-400">Typed code · not synced with board</span>
        ) : activeView === "transcript" ? (
          <span className="text-xs text-stone-400">{board ? `Read-only · pass ${board.pass}` : "Read-only"}</span>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-stone-400">{notesSaved ? "Saved" : "Unsaved"}</span>
            <button
              type="button"
              onClick={saveNotes}
              disabled={notesSaved}
              className="rounded border border-stone-300 px-2 py-1 text-xs font-medium text-stone-700 enabled:hover:bg-stone-100 disabled:opacity-50"
            >
              Save notes
            </button>
          </div>
        )}
      </header>
      {activeView === "editor" ? (
        <EditorTab sessionId={sessionId} problemId={problemId} board={board}
                   submission={submission} onSubmitted={onSubmitted} />
      ) : activeView === "notes" ? (
        <textarea
          aria-label="Session notes"
          value={notes}
          onChange={(event) => {
            setNotes(event.target.value);
            setNotesSaved(false);
          }}
          placeholder="Write your notes here…"
          className="min-h-0 flex-1 resize-none bg-[#fbfcfa] p-4 text-sm leading-6 text-stone-800 outline-none placeholder:text-stone-400 focus:bg-white"
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto bg-[#fbfcfa] p-4 font-mono text-sm leading-6 text-stone-800">
          {!board && <p className="font-sans text-stone-400">Transcribed whiteboard text will appear here.</p>}
          {[...codeRegions, ...otherRegions].map((region) => (
            <div key={region.id} className="mb-4">
              <p className="mb-1 font-sans text-[11px] uppercase tracking-wide text-stone-400">
                {region.id} · {region.type}
              </p>
              {region.lines.map((line) => (
                <div
                  key={line.n}
                  className={`flex gap-3 ${
                    highlight && highlight.regionId === region.id && (highlight.line === line.n || highlight.line === 0)
                      ? "rounded bg-amber-100 ring-1 ring-amber-400"
                      : ""
                  }`}
                >
                  <span className="w-6 shrink-0 select-none text-right text-stone-400">{line.n}</span>
                  <span
                    className={`whitespace-pre-wrap ${line.corrected ? "underline decoration-amber-500 decoration-dotted underline-offset-4" : ""}`}
                    title={line.corrected ? `Transcriber read: ${line.transcribedText ?? ""}` : undefined}
                  >
                    {line.text}
                  </span>
                </div>
              ))}
            </div>
          ))}
          {board && board.findings.length > 0 && (
            <details className="mt-4 font-sans text-xs text-stone-500">
              <summary className="cursor-pointer select-none">Debug: {board.findings.filter((f) => f.status !== "resolved").length} open findings</summary>
              <ul className="mt-2 space-y-1">
                {board.findings.map((finding) => (
                  <li key={finding.id} className={finding.status === "resolved" ? "opacity-50" : ""}>
                    t{finding.severity} · L{finding.line} · {finding.status} · {finding.confidence.toFixed(2)} — {finding.message}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
