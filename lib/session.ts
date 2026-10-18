import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { createSession, endSession, sessionSocketUrl } from "@/lib/api";
import { captureFrame } from "@/lib/capture";
import type { BoardState, GateEvent, ServerEvent, StatusEvent } from "@/lib/types";

const FRAMES_PER_SECOND = 2;
const MAX_BUFFERED_BYTES = 2_000_000;

export interface VoiceSession {
  start(): Promise<void>;
  end(): Promise<void>;
  sendContext(context: string): Promise<void>;
}

// TODO Phase 3: connect a voice session to the Gemini Live service.
export const noopVoiceSession: VoiceSession = {
  start: async () => {},
  end: async () => {},
  sendContext: async () => {},
};

/**
 * Streams camera frames to the backend vision loop and tracks the board state
 * it sends back. Call start() after the camera is playing.
 */
export function useBoardSession(problemId: string, videoRef: RefObject<HTMLVideoElement | null>) {
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [board, setBoard] = useState<BoardState | null>(null);
  const [gate, setGate] = useState<GateEvent | null>(null);
  const [status, setStatus] = useState<StatusEvent | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const teardown = useCallback(() => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
    socketRef.current?.close();
    socketRef.current = null;
  }, []);

  const start = useCallback(async () => {
    setConnectionError(null);
    setBoard(null);
    setGate(null);
    setStatus(null);
    canvasRef.current ??= document.createElement("canvas");

    let id: string;
    try {
      id = await createSession(problemId);
    } catch (err) {
      setConnectionError(`Could not reach the backend: ${err instanceof Error ? err.message : err}`);
      return;
    }
    setSessionId(id);

    const socket = new WebSocket(sessionSocketUrl(id));
    socketRef.current = socket;
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as ServerEvent;
      if (event.type === "boardState") setBoard(event);
      else if (event.type === "gate") setGate(event);
      else if (event.type === "status") setStatus(event);
    };
    socket.onerror = () => setConnectionError("Lost connection to the backend.");
    socket.onopen = () => {
      timerRef.current = window.setInterval(() => {
        const video = videoRef.current;
        const canvas = canvasRef.current;
        if (!video || !canvas || socket.readyState !== WebSocket.OPEN) return;
        if (socket.bufferedAmount > MAX_BUFFERED_BYTES) return;
        const frame = captureFrame(video, canvas);
        if (frame) socket.send(JSON.stringify({ type: "frame", ...frame }));
      }, 1000 / FRAMES_PER_SECOND);
    };
  }, [problemId, videoRef]);

  const stop = useCallback(async () => {
    teardown();
    if (sessionId) await endSession(sessionId).catch(() => {});
  }, [sessionId, teardown]);

  useEffect(() => teardown, [teardown]);

  return { sessionId, board, gate, status, connectionError, start, stop };
}
