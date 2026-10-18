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
  /** Normalized 0-1 box around this line, when the transcriber provided one. */
  bbox?: { x: number; y: number; width: number; height: number };
}

export interface Region {
  id: string;
  type: "code" | "heading" | "diagram" | "examples" | "trace";
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
  /** True when regions are newer than findings (analyzer still running on this text). */
  analysisPending: boolean;
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

export interface HighlightEvent {
  type: "highlight";
  regionId: string;
  /** 0 means the whole region. */
  line: number;
}

export interface InterjectionRelease {
  findingId: string;
  regionId: string;
  line: number;
  tier: 1 | 2 | 3;
  category: string;
  mode: "statement" | "question";
  /** Send to the voice model as "INTERJECT: " + instruction. Never contains the fix. */
  instruction: string;
}

export type SessionPhase = "clarifying" | "writing" | "tracing" | "done";

export type DiffOp = "same" | "formatting" | "changed" | "added" | "removed";

export interface DiffLine {
  op: DiffOp;
  boardLine: number | null;
  typedLine: number | null;
  boardText: string | null;
  typedText: string | null;
}

/** Typed code takes priority; boardSnapshot is the board at the first submit. */
export interface Submission {
  type: "submission";
  submittedAt: string;
  language: string | null;
  boardSnapshot: string[];
  typedCode: string[];
  diff: DiffLine[];
  counts: Record<DiffOp, number>;
  review: {
    summary: string;
    findings: { tier: 1 | 2 | 3 | 4; category: string; line: number; confidence: number; message: string }[];
  } | null;
  reviewProvider: string | null;
  reviewModel: string | null;
  reviewLatencyS: number | null;
  reviewError: string | null;
  changedAfterBoard: boolean;
}

export type ServerEvent = BoardState | GateEvent | StatusEvent | HighlightEvent | Submission;

export interface TranscriptTurn {
  role: "candidate" | "interviewer";
  text: string;
  timestamp: string;
}
