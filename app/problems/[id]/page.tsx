"use client";

import Link from "next/link";
import { notFound } from "next/navigation";
import { use, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import problems from "@/data/problems.json";
import { BoardPanel, CameraPanel } from "@/app/problems/[id]/board-panels";
import { VoiceStrip } from "@/app/problems/[id]/voice-panel";
import ThemeToggle from "@/app/theme-toggle";
import { useCamera } from "@/lib/capture";
import { useBoardSession } from "@/lib/session";
import { useVoiceSession } from "@/lib/voice";

type Problem = (typeof problems)[number];

type ResizeTarget = "columns" | "rows";

type PreviousAttempt = {
  id: string;
  startedAt: string;
  endedAt: string;
  durationSeconds: number;
  boardPass: number;
  findingCount: number;
  aiReview?: { summary: string; reviewedAt: string } | null;
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function formatDuration(totalSeconds: number) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}h ${minutes}m ${seconds}s`
    : minutes > 0
      ? `${minutes}m ${seconds}s`
      : `${seconds}s`;
}

function SessionView({ problem }: { problem: Problem }) {
  const workspaceRef = useRef<HTMLDivElement>(null);
  const sideRef = useRef<HTMLDivElement>(null);
  const [promptWidth, setPromptWidth] = useState(62);
  const [videoHeight, setVideoHeight] = useState(54);
  const [resizeTarget, setResizeTarget] = useState<ResizeTarget | null>(null);
  const camera = useCamera();
  const boardSession = useBoardSession(problem.id, camera.videoRef);
  const voice = useVoiceSession();
  const [isSessionActive, setIsSessionActive] = useState(false);
  const [hasSessionStarted, setHasSessionStarted] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [promptTab, setPromptTab] = useState<"prompt" | "attempts">("prompt");
  const [attempts, setAttempts] = useState<PreviousAttempt[]>([]);
  const [attemptsLoaded, setAttemptsLoaded] = useState(false);
  const sessionStartedAt = useRef<number | null>(null);
  const sessionStartedForVisit = useRef(false);
  const attemptsStorageKey = `leetplusplus:attempts:${problem.id}`;

  useEffect(() => {
    try {
      const savedAttempts: unknown = JSON.parse(window.localStorage.getItem(attemptsStorageKey) ?? "[]");
      if (Array.isArray(savedAttempts)) {
        setAttempts(savedAttempts.filter((attempt): attempt is PreviousAttempt =>
          typeof attempt?.id === "string" &&
          typeof attempt?.startedAt === "string" &&
          typeof attempt?.endedAt === "string" &&
          typeof attempt?.durationSeconds === "number" &&
          typeof attempt?.boardPass === "number" &&
          typeof attempt?.findingCount === "number"
        ));
      }
    } catch {
      setAttempts([]);
    }
    setAttemptsLoaded(true);
  }, [attemptsStorageKey]);

  useEffect(() => {
    if (!attemptsLoaded) return;
    try {
      window.localStorage.setItem(attemptsStorageKey, JSON.stringify(attempts));
    } catch {
      // Keep the current page usable when browser storage is unavailable.
    }
  }, [attempts, attemptsLoaded, attemptsStorageKey]);

  useEffect(() => {
    if (!isSessionActive) return;

    const timer = window.setInterval(() => {
      if (sessionStartedAt.current !== null) {
        setElapsedSeconds(Math.floor((Date.now() - sessionStartedAt.current) / 1000));
      }
    }, 1000);

    return () => window.clearInterval(timer);
  }, [isSessionActive]);

  async function beginSession() {
    if (sessionStartedForVisit.current) return;
    sessionStartedForVisit.current = true;
    try {
      await camera.start();
    } catch {
      sessionStartedForVisit.current = false;
      return; // camera.error is shown in the camera panel
    }
    sessionStartedAt.current = Date.now();
    setElapsedSeconds(0);
    setHasSessionStarted(true);
    setIsSessionActive(true);
    const sessionId = await boardSession.start();
    if (sessionId) await voice.start(sessionId);
  }

  async function endSession() {
    const endedAt = Date.now();
    const startedAt = sessionStartedAt.current;
    if (startedAt !== null) {
      const durationSeconds = Math.floor((endedAt - startedAt) / 1000);
      setElapsedSeconds(durationSeconds);
      setAttempts((previousAttempts) => [{
        id: `${endedAt}-${Math.random().toString(36).slice(2, 8)}`,
        startedAt: new Date(startedAt).toISOString(),
        endedAt: new Date(endedAt).toISOString(),
        durationSeconds,
        boardPass: boardSession.board?.pass ?? 0,
        findingCount: boardSession.board?.findings.length ?? 0,
        aiReview: null,
      }, ...previousAttempts]);
      sessionStartedAt.current = null;
    }
    setIsSessionActive(false);
    voice.stop();
    camera.stop();
    await boardSession.stop();
  }

  const hours = Math.floor(elapsedSeconds / 3600);
  const minutes = Math.floor((elapsedSeconds % 3600) / 60);
  const seconds = elapsedSeconds % 60;
  const formattedTime = hours > 0
    ? `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`
    : `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;

  function startResize(target: ResizeTarget, event: PointerEvent<HTMLDivElement>) {
    setResizeTarget(target);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function resizeByKeyboard(target: ResizeTarget, event: KeyboardEvent<HTMLDivElement>) {
    const isForward = target === "columns" ? event.key === "ArrowRight" : event.key === "ArrowDown";
    const isBackward = target === "columns" ? event.key === "ArrowLeft" : event.key === "ArrowUp";
    if (!isForward && !isBackward) return;

    event.preventDefault();
    const amount = isForward ? 4 : -4;
    if (target === "columns") setPromptWidth((width) => clamp(width + amount, 38, 76));
    else setVideoHeight((height) => clamp(height + amount, 30, 70));
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    if (resizeTarget === "columns" && workspaceRef.current) {
      const { left, width } = workspaceRef.current.getBoundingClientRect();
      setPromptWidth(clamp(((event.clientX - left) / width) * 100, 38, 76));
    }
    if (resizeTarget === "rows" && sideRef.current) {
      const { top, height } = sideRef.current.getBoundingClientRect();
      setVideoHeight(clamp(((event.clientY - top) / height) * 100, 30, 70));
    }
  }

  return (
    <main className="coding-workspace flex h-[100dvh] flex-col overflow-hidden bg-[#f7f8f5]">
      <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-stone-200 px-2 sm:px-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/" className="shrink-0 text-base font-bold tracking-tight text-[#17211d]">
            leet<span className="text-emerald-700">++</span>
          </Link>
          <span className="truncate border-l border-stone-300 pl-3 text-sm font-medium text-stone-700">{problem.title}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ThemeToggle />
          {hasSessionStarted && (
            <output className="min-w-12 text-center font-mono text-xs tabular-nums text-stone-700" aria-label="Elapsed session time" aria-live="off">
              {formattedTime}
            </output>
          )}
          {isSessionActive ? (
            <button type="button" onClick={endSession} className="rounded border border-stone-300 px-2 py-1.5 text-xs font-semibold text-stone-700 hover:bg-white sm:px-3">
              End session
            </button>
          ) : hasSessionStarted ? (
            <span role="status" className="rounded border border-stone-300 px-2 py-1.5 text-xs font-semibold text-stone-500 sm:px-3">
              Session ended
            </span>
          ) : (
            <button
              type="button"
              onClick={beginSession}
              className="rounded bg-[#174d3b] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#103c2e]"
            >
              Begin Session
            </button>
          )}
        </div>
      </header>
      <VoiceStrip voice={voice} />
      <div
        ref={workspaceRef}
        className="workspace-grid min-h-0 flex-1"
        style={{ "--prompt-ratio": `${promptWidth}fr`, "--side-ratio": `${100 - promptWidth}fr` } as React.CSSProperties}
        onPointerMove={handlePointerMove}
        onPointerUp={() => setResizeTarget(null)}
        onPointerCancel={() => setResizeTarget(null)}
      >
        <article className="workspace-prompt min-h-0 overflow-y-auto border-r border-stone-200 bg-[#fbfcfa] px-3 py-4 sm:px-4">
          <div className="w-full">
            <div className="flex items-center gap-1 border-b border-stone-200" role="group" aria-label="Prompt views">
              <button
                type="button"
                aria-pressed={promptTab === "prompt"}
                onClick={() => setPromptTab("prompt")}
                className={`border-b-2 px-3 py-2 text-sm font-medium ${promptTab === "prompt" ? "border-emerald-700 text-emerald-800" : "border-transparent text-stone-500 hover:text-stone-800"}`}
              >
                Prompt
              </button>
              <button
                type="button"
                aria-pressed={promptTab === "attempts"}
                onClick={() => setPromptTab("attempts")}
                className={`border-b-2 px-3 py-2 text-sm font-medium ${promptTab === "attempts" ? "border-emerald-700 text-emerald-800" : "border-transparent text-stone-500 hover:text-stone-800"}`}
              >
                Previous attempts <span className="ml-1 text-xs text-stone-400">{attempts.length}</span>
              </button>
            </div>
            {promptTab === "prompt" ? (
              <>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <span className="rounded bg-stone-200 px-2 py-1 text-xs font-semibold text-stone-700">{problem.difficulty}</span>
                  {problem.patterns.map((pattern) => (
                    <span key={pattern} className="border border-stone-300 px-2 py-1 text-xs text-stone-600">{pattern}</span>
                  ))}
                </div>
                <h1 className="mt-4 text-2xl font-semibold tracking-tight text-[#17211d] sm:text-3xl">{problem.title}</h1>
                <p className="mt-5 max-w-3xl text-base leading-7 text-stone-700">{problem.prompt.description}</p>

                <section className="mt-8" aria-labelledby="examples-heading">
                  <h2 id="examples-heading" className="text-sm font-semibold text-[#17211d]">Examples</h2>
                  <div className="mt-3 space-y-3">
                    {problem.prompt.examples.map((example) => (
                      <div key={example.input} className="border-l-2 border-emerald-700 bg-white px-4 py-3">
                        <p className="font-mono text-sm leading-6 text-stone-800"><span className="font-sans font-semibold">Input:</span> {example.input}</p>
                        <p className="font-mono text-sm leading-6 text-stone-800"><span className="font-sans font-semibold">Output:</span> {example.output}</p>
                        <p className="mt-1 text-sm leading-6 text-stone-600">{example.explanation}</p>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="mt-8 pb-6" aria-labelledby="constraints-heading">
                  <h2 id="constraints-heading" className="text-sm font-semibold text-[#17211d]">Constraints &amp; goals</h2>
                  <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-stone-700">
                    {problem.prompt.constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}
                  </ul>
                </section>
              </>
            ) : (
              <section className="pt-5" aria-label="Previous attempts">
                {attempts.length === 0 ? (
                  <p className="text-sm text-stone-500">No previous attempts yet.</p>
                ) : (
                  <ol className="divide-y divide-stone-200">
                    {attempts.map((attempt) => (
                      <li key={attempt.id} className="py-4 first:pt-0">
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <time dateTime={attempt.endedAt} className="text-sm font-semibold text-[#17211d]">
                            {new Date(attempt.endedAt).toLocaleString()}
                          </time>
                          <span className="text-xs text-stone-500">{formatDuration(attempt.durationSeconds)}</span>
                        </div>
                        <p className="mt-1 text-xs text-stone-500">
                          {attempt.boardPass} board {attempt.boardPass === 1 ? "pass" : "passes"} · {attempt.findingCount} {attempt.findingCount === 1 ? "finding" : "findings"}
                        </p>
                        {attempt.aiReview && (
                          <section className="mt-3 border-l-2 border-emerald-700 pl-3" aria-label="AI review">
                            <h2 className="text-xs font-semibold text-stone-700">AI review</h2>
                            <p className="mt-1 text-sm leading-6 text-stone-600">{attempt.aiReview.summary}</p>
                            <time dateTime={attempt.aiReview.reviewedAt} className="mt-1 block text-xs text-stone-400">
                              {new Date(attempt.aiReview.reviewedAt).toLocaleString()}
                            </time>
                          </section>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            )}
          </div>
        </article>

        <div
          role="separator"
          aria-label="Resize prompt and workspace panels"
          aria-orientation="vertical"
          aria-valuemin={38}
          aria-valuemax={76}
          aria-valuenow={Math.round(promptWidth)}
          tabIndex={0}
          className="workspace-resizer hidden lg:flex"
          onPointerDown={(event) => startResize("columns", event)}
          onKeyDown={(event) => resizeByKeyboard("columns", event)}
        />

        <div
          ref={sideRef}
          className="workspace-side min-h-0 bg-white"
          style={{ "--video-ratio": `${videoHeight}fr`, "--editor-ratio": `${100 - videoHeight}fr` } as React.CSSProperties}
        >
          <CameraPanel
            camera={camera}
            regions={boardSession.board?.regions ?? []}
            gate={boardSession.gate}
            status={boardSession.status}
            error={camera.error ?? boardSession.connectionError}
            sessionEnded={hasSessionStarted && !isSessionActive}
          />

          <div
            role="separator"
            aria-label="Resize camera and transcript panels"
            aria-orientation="horizontal"
            aria-valuemin={30}
            aria-valuemax={70}
            aria-valuenow={Math.round(videoHeight)}
            tabIndex={0}
            className="workspace-resizer hidden lg:flex"
            onPointerDown={(event) => startResize("rows", event)}
            onKeyDown={(event) => resizeByKeyboard("rows", event)}
          />

          <BoardPanel board={boardSession.board} problemId={problem.id} highlight={voice.highlight} />
        </div>
      </div>
    </main>
  );
}

export default function ProblemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const problem = (problems as Problem[]).find((item) => item.id === id);

  if (!problem) notFound();

  return <SessionView problem={problem} />;
}