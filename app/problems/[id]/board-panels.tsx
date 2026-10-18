"use client";

import type { useCamera } from "@/lib/capture";
import type { BoardState, GateEvent, Region, StatusEvent } from "@/lib/types";

type Camera = ReturnType<typeof useCamera>;

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
}: {
  camera: Camera;
  regions: Region[];
  gate: GateEvent | null;
  status: StatusEvent | null;
  error: string | null;
}) {
  return (
    <section className="flex min-h-0 flex-col" aria-label="Camera feed">
      <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-stone-200 px-4">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-stone-600">Camera feed</h2>
        {camera.isActive ? (
          <div className="flex items-center gap-1.5" aria-live="polite">
            <Pill on={!!gate?.changed} label="changed" />
            <Pill on={!!gate?.stable} label="stable" />
            <span className="ml-1 text-xs text-stone-500">{status ? STAGE_LABEL[status.stage] : "Waiting…"}</span>
          </div>
        ) : (
          <span className="text-xs text-stone-400">Preview</span>
        )}
      </header>
      <div className="flex min-h-0 flex-1 items-center justify-center bg-[#e9ece7] p-3">
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
        </div>
      </div>
      {camera.isActive && error && <p className="border-t border-stone-200 px-4 py-2 text-xs text-red-700">{error}</p>}
      {status?.stage === "error" && status.detail && (
        <p className="border-t border-stone-200 px-4 py-2 text-xs text-red-700">{status.detail}</p>
      )}
    </section>
  );
}

export function BoardPanel({ board }: { board: BoardState | null }) {
  const codeRegions = board?.regions.filter((region) => region.type === "code") ?? [];
  const otherRegions = board?.regions.filter((region) => region.type !== "code") ?? [];

  return (
    <section className="flex min-h-[240px] flex-col border-t border-stone-200 lg:min-h-0" aria-label="Board transcript">
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-stone-200 px-4">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-stone-600">Board transcript</h2>
        <span className="text-xs text-stone-400">{board ? `Read-only · pass ${board.pass}` : "Read-only"}</span>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto bg-[#fbfcfa] p-4 font-mono text-sm leading-6 text-stone-800">
        {!board && <p className="font-sans text-stone-400">Transcribed whiteboard text will appear here.</p>}
        {[...codeRegions, ...otherRegions].map((region) => (
          <div key={region.id} className="mb-4">
            <p className="mb-1 font-sans text-[11px] uppercase tracking-wide text-stone-400">
              {region.id} · {region.type}
            </p>
            {region.lines.map((line) => (
              <div key={line.n} className="flex gap-3">
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
    </section>
  );
}
