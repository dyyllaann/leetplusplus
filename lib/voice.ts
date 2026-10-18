import { useCallback, useEffect, useRef, useState } from "react";
import { voiceSocketUrl } from "@/lib/api";

// Wire format (docs/api.md): we send 16 kHz mono PCM16, the backend sends 24 kHz mono PCM16.
const INPUT_RATE = 16000;
const OUTPUT_RATE = 24000;
const SAMPLES_PER_CHUNK = 640; // 40 ms at 16 kHz

const CAPTURE_WORKLET = `
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor("pcm-capture", Capture);
`;

export interface VoiceTurn {
  role: "candidate" | "interviewer";
  text: string;
}

export interface Highlight {
  regionId: string;
  line: number;
  at: number;
}

export type VoiceState = "off" | "connecting" | "live" | "error";

function floatToPcm16(samples: Float32Array): ArrayBuffer {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}

export function useVoiceSession() {
  const socketRef = useRef<WebSocket | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const inputCtxRef = useRef<AudioContext | null>(null);
  const outputCtxRef = useRef<AudioContext | null>(null);
  const playheadRef = useRef(0);
  const playingRef = useRef<AudioBufferSourceNode[]>([]);
  const [state, setState] = useState<VoiceState>("off");
  const [error, setError] = useState<string | null>(null);
  const [turns, setTurns] = useState<VoiceTurn[]>([]);
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const [pushToTalk, setPushToTalk] = useState(false);
  const [interviewerSpeaking, setInterviewerSpeaking] = useState(false);

  const stopPlayback = useCallback(() => {
    playingRef.current.forEach((source) => {
      try { source.stop(); } catch { /* already stopped */ }
    });
    playingRef.current = [];
    playheadRef.current = 0;
    setInterviewerSpeaking(false);
  }, []);

  const playChunk = useCallback((data: ArrayBuffer) => {
    const ctx = outputCtxRef.current;
    if (!ctx) return;
    const pcm = new Int16Array(data);
    const buffer = ctx.createBuffer(1, pcm.length, OUTPUT_RATE);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const startAt = Math.max(ctx.currentTime + 0.02, playheadRef.current);
    source.start(startAt);
    playheadRef.current = startAt + buffer.duration;
    playingRef.current.push(source);
    setInterviewerSpeaking(true);
    source.onended = () => {
      playingRef.current = playingRef.current.filter((s) => s !== source);
      if (playingRef.current.length === 0) setInterviewerSpeaking(false);
    };
  }, []);

  const stop = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
    stopPlayback();
    inputCtxRef.current?.close().catch(() => {});
    outputCtxRef.current?.close().catch(() => {});
    inputCtxRef.current = null;
    outputCtxRef.current = null;
    setState("off");
  }, [stopPlayback]);

  const start = useCallback(async (sessionId: string) => {
    setError(null);
    setTurns([]);
    setHighlight(null);
    setState("connecting");
    try {
      const mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      micStreamRef.current = mic;
      // The browser resamples the mic to the context rate, so the worklet sees 16 kHz.
      const inputCtx = new AudioContext({ sampleRate: INPUT_RATE });
      const outputCtx = new AudioContext({ sampleRate: OUTPUT_RATE });
      inputCtxRef.current = inputCtx;
      outputCtxRef.current = outputCtx;
      const workletUrl = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: "application/javascript" }));
      await inputCtx.audioWorklet.addModule(workletUrl);
      URL.revokeObjectURL(workletUrl);

      const socket = new WebSocket(voiceSocketUrl(sessionId));
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;

      const node = new AudioWorkletNode(inputCtx, "pcm-capture");
      let pending = new Float32Array(0);
      node.port.onmessage = (event: MessageEvent<Float32Array>) => {
        const merged = new Float32Array(pending.length + event.data.length);
        merged.set(pending);
        merged.set(event.data, pending.length);
        pending = merged;
        while (pending.length >= SAMPLES_PER_CHUNK) {
          if (socket.readyState === WebSocket.OPEN) socket.send(floatToPcm16(pending.slice(0, SAMPLES_PER_CHUNK)));
          pending = pending.slice(SAMPLES_PER_CHUNK);
        }
      };
      inputCtx.createMediaStreamSource(mic).connect(node);

      socket.onmessage = (message) => {
        if (message.data instanceof ArrayBuffer) {
          playChunk(message.data);
          return;
        }
        const event = JSON.parse(message.data);
        if (event.type === "voiceStatus") {
          if (event.state === "connected") {
            setState("live");
            setPushToTalk(!!event.pushToTalk);
          } else if (event.state === "error") {
            setState("error");
            setError(event.detail ?? "Voice session failed");
          }
        } else if (event.type === "interrupted") {
          stopPlayback();
        } else if (event.type === "transcript") {
          setTurns((previous) => [...previous, { role: event.role, text: event.text }]);
        } else if (event.type === "highlight") {
          setHighlight({ regionId: event.regionId, line: event.line, at: Date.now() });
        }
      };
      socket.onclose = () => setState((current) => (current === "error" ? current : "off"));
      socket.onerror = () => {
        setState("error");
        setError("Lost connection to the voice backend.");
      };
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [playChunk, stopPlayback]);

  const setTalking = useCallback((talking: boolean) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "ptt", state: talking ? "down" : "up" }));
    }
  }, []);

  useEffect(() => stop, [stop]);

  return { state, error, turns, highlight, pushToTalk, interviewerSpeaking, start, stop, setTalking };
}
