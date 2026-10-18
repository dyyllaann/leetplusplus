// Vision-loop contract. Source of truth: docs/api.md.

export interface CapturedFrame {
  capturedAt: string;
  imageData: string;
}

export interface BoardLine {
  n: number;
  text: string;
  lowConfidenceChars: number[];
  /** True when the analyzer read the image differently from the transcriber. */
  corrected: boolean;
  transcribedText?: string;
}

export interface Region {
  id: string;
  type: "code" | "diagram" | "examples" | "trace";
  /** Normalized 0-1 relative to the frame. */
  bbox: { x: number; y: number; width: number; height: number };
  lines: BoardLine[];
}

export type FindingStatus = "new" | "queued" | "released" | "resolved";

export interface Finding {
  id: string;
  regionId: string;
  line: number;
  severity: 1 | 2 | 3 | 4;
  category: string;
  confidence: number;
  /** Debug only: may name the fix, never show to the candidate. */
  message: string;
  status: FindingStatus;
}

export interface BoardState {
  type: "boardState";
  pass: number;
  updatedAt: string | null;
  regions: Region[];
  findings: Finding[];
}

export interface GateEvent {
  type: "gate";
  changed: boolean;
  stable: boolean;
  busy: boolean;
}

export type PipelineStage = "transcribing" | "analyzing" | "idle" | "error";

export interface StatusEvent {
  type: "status";
  stage: PipelineStage;
  detail?: string;
}

export type ServerEvent = BoardState | GateEvent | StatusEvent;

export interface TranscriptTurn {
  role: "candidate" | "interviewer";
  text: string;
  timestamp: string;
}
