import type { CapturedFrame } from "@/lib/types";

export interface FrameSink {
  pushFrame(frame: CapturedFrame): Promise<void>;
  close(): Promise<void>;
}

export interface VoiceSession {
  start(): Promise<void>;
  end(): Promise<void>;
  sendContext(context: string): Promise<void>;
}

// TODO Phase 1: connect the frame sink to the vision loop.
export const noopFrameSink: FrameSink = {
  pushFrame: async () => {},
  close: async () => {},
};

// TODO Phase 3: connect a voice session to the Gemini Live service.
export const noopVoiceSession: VoiceSession = {
  start: async () => {},
  end: async () => {},
  sendContext: async () => {},
};