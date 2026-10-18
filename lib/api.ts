// REST calls to the FastAPI backend (docs/api.md).

export const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export function sessionSocketUrl(sessionId: string): string {
  return `${BACKEND_URL.replace(/^http/, "ws")}/sessions/${sessionId}/ws`;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export async function createSession(problemId: string): Promise<string> {
  const { sessionId } = await post<{ sessionId: string }>("/sessions", { problemId });
  return sessionId;
}

export function endSession(sessionId: string): Promise<{ ok: boolean }> {
  return post(`/sessions/${sessionId}/end`, {});
}

export function triggerAnalysis(sessionId: string, reason: string): Promise<{ ok: boolean }> {
  return post(`/sessions/${sessionId}/trigger`, { reason });
}

export interface SyncResult {
  /** False if the timeout passed before the transcription caught up with the board. */
  fresh: boolean;
  boardState: import("@/lib/types").BoardState;
}

/**
 * Wait until the board transcription is current. Call at the end of every candidate turn,
 * before the voice agent replies; if `fresh` is false, have it say a short holding line.
 */
export function syncBoard(sessionId: string, timeoutSeconds = 2.5): Promise<SyncResult> {
  return post(`/sessions/${sessionId}/sync`, { timeoutSeconds });
}
