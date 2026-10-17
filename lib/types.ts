// TODO Phase 1: replace placeholder shapes with the vision-loop contract.
export interface CapturedFrame {
  capturedAt: string;
  imageData: string;
}

export interface Region {
  id: string;
  type: string;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}

export interface Finding {
  id: string;
  regionId: string;
  severity: 1 | 2 | 3 | 4;
  confidence: number;
  message: string;
}

export interface TranscriptTurn {
  role: "candidate" | "interviewer";
  text: string;
  timestamp: string;
}