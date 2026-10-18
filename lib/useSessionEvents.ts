import { useEffect, useRef, useState } from "react";
import { sessionSocketUrl } from "@/lib/api";
import type { HighlightEvent, ServerEvent, Submission } from "@/lib/types";

const HIGHLIGHT_MS = 6000;

/**
 * Listens on a separate, read-only WebSocket for events the frame socket does not handle:
 * voice-agent highlights and code submissions. It never sends frames, so it is safe to
 * run next to useBoardSession (the backend broadcasts every event to all subscribers).
 */
export function useSessionEvents(sessionId: string | null) {
  const [highlight, setHighlight] = useState<HighlightEvent | null>(null);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const clearTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    const socket = new WebSocket(sessionSocketUrl(sessionId));
    socket.onmessage = (message) => {
      let event: ServerEvent;
      try {
        event = JSON.parse(message.data) as ServerEvent;
      } catch {
        return;
      }
      if (event.type === "highlight") {
        setHighlight(event);
        if (clearTimer.current !== null) window.clearTimeout(clearTimer.current);
        clearTimer.current = window.setTimeout(() => setHighlight(null), HIGHLIGHT_MS);
      } else if (event.type === "submission") {
        setSubmission(event);
      }
    };
    return () => {
      socket.close();
      if (clearTimer.current !== null) window.clearTimeout(clearTimer.current);
    };
  }, [sessionId]);

  return { highlight, submission, setSubmission, clearHighlight: () => setHighlight(null) };
}
