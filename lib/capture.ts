import type { CapturedFrame } from "@/lib/types";

// TODO Phase 1: connect browser camera access and gated frame capture.
export function useCamera() {
  return {
    videoRef: { current: null as HTMLVideoElement | null },
    isActive: false,
    start: async () => {},
    stop: () => {},
  };
}

// TODO Phase 1: capture stable, changed, unobstructed whiteboard frames.
export function useFrameCapture() {
  return {
    isCapturing: false,
    captureFrame: async (): Promise<CapturedFrame | null> => null,
  };
}