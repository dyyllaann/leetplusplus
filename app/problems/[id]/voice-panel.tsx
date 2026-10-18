"use client";

import type { useVoiceSession } from "@/lib/voice";

type Voice = ReturnType<typeof useVoiceSession>;

const STATE_LABEL: Record<Voice["state"], string> = {
  off: "Interviewer off",
  connecting: "Connecting interviewer…",
  live: "Interviewer listening",
  error: "Interviewer error",
};

/** Slim strip under the header: interviewer status, latest line, push-to-talk. */
export function VoiceStrip({ voice }: { voice: Voice }) {
  const last = voice.turns.at(-1);
  const lastInterviewer = [...voice.turns].reverse().find((turn) => turn.role === "interviewer");
  const shown = voice.interviewerSpeaking ? lastInterviewer ?? last : last;

  if (voice.state === "off" && voice.turns.length === 0) return null;

  return (
    <div className="flex min-h-10 shrink-0 items-center gap-3 border-b border-stone-200 bg-white px-3 py-1.5 text-sm" aria-live="polite">
      <span
        className={`h-2.5 w-2.5 shrink-0 rounded-full ${
          voice.state === "live"
            ? voice.interviewerSpeaking ? "animate-pulse bg-emerald-600" : "bg-emerald-600"
            : voice.state === "error" ? "bg-red-600" : "bg-stone-300"
        }`}
        aria-hidden
      />
      <span className="shrink-0 text-xs font-semibold text-stone-600">
        {voice.interviewerSpeaking ? "Interviewer speaking" : STATE_LABEL[voice.state]}
      </span>
      <p className="min-w-0 flex-1 truncate text-stone-700">
        {voice.error ? <span className="text-red-700">{voice.error}</span> : shown ? (
          <><span className="font-medium">{shown.role === "interviewer" ? "Interviewer: " : "You: "}</span>{shown.text}</>
        ) : null}
      </p>
      {voice.pushToTalk && voice.state === "live" && (
        <button
          type="button"
          onPointerDown={() => voice.setTalking(true)}
          onPointerUp={() => voice.setTalking(false)}
          onPointerLeave={() => voice.setTalking(false)}
          className="shrink-0 rounded bg-[#174d3b] px-3 py-1 text-xs font-semibold text-white active:bg-[#103c2e]"
        >
          Hold to talk
        </button>
      )}
    </div>
  );
}
