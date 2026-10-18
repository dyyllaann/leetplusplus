# Backend API contract (frontend <-> FastAPI)

Backend runs at `http://localhost:8000` (`.venv/bin/uvicorn backend.app:app --reload --port 8000`).
CORS allows `http://localhost:3000`. All JSON keys are camelCase.

Owner of this file: backend. Frontend: please request changes rather than editing it directly.

## REST

### `GET /problems`
Response: `[{ "id": "two-sum", "title": "Two Sum" }, ...]`

### `GET /debug/camera`
Backend-served webcam test page (not part of the product UI).

### `POST /sessions`
Request: `{ "problemId": "two-sum" }` (an `id` from `data/problems.json`)
Response: `{ "sessionId": "a1b2c3d4" }`

### `GET /sessions/{sessionId}`
Response: the latest `boardState` event payload (see below), or 404.

### `POST /sessions/{sessionId}/trigger`
Request: `{ "reason": "candidate_stopped_speaking" }`
Asks for an analysis pass as soon as the board is stable, skipping the analysis interval
(5 s, measured from the start of the previous pass).
Response: `{ "ok": true }`

### `POST /sessions/{sessionId}/sync`
Request: `{ "timeoutSeconds": 2.5 }` (capped at 10)
Waits until the transcription reflects the board as it is now (no unanalyzed change and no
transcription in flight), then returns. Skips the analysis interval if a change is waiting.
Response: `{ "fresh": true, "boardState": { ...boardState payload... } }`
`fresh: false` means the timeout passed first (candidate still writing, or a slow model call);
`boardState` is then the latest available. **The voice layer must call this at the end of each
candidate turn before generating a reply**, and say a short holding line if `fresh` is false.

## Code submission (backend/submission.py)

The board tab (live transcription) and the editor tab (typed code) are never synced.
The editor may copy the board once ("Copy from board", client-side); nothing flows back.

### `POST /sessions/{sessionId}/submit`
Request: `{ "code": "typed code as one string", "language": "python" }`
The typed code takes priority. The first submit takes a board snapshot (code regions only,
in reading order) and stops camera updates; later submits replace only the typed code and
re-diff, so the editor stays editable. Sets the phase to `done`.
Response (also pushed on the WebSocket):
```json
{
  "type": "submission",
  "submittedAt": "2026-10-18T07:40:00+00:00",
  "language": "python",
  "boardSnapshot": ["def f(a):", "  if x < 0:"],
  "typedCode": ["def f(a):", "    if x <= 0:"],
  "diff": [
    { "op": "same", "boardLine": 1, "typedLine": 1, "boardText": "def f(a):", "typedText": "def f(a):" },
    { "op": "changed", "boardLine": 2, "typedLine": 2, "boardText": "  if x < 0:", "typedText": "    if x <= 0:" }
  ],
  "counts": { "same": 1, "formatting": 0, "changed": 1, "added": 0, "removed": 0 },
  "changedAfterBoard": true
}
```
`op`: `same`, `formatting` (whitespace only), `changed`, `added` (typed only), `removed`
(board only). `changedAfterBoard` is true when anything beyond whitespace differs.

### `GET /sessions/{sessionId}/submission`
The latest submission payload, or 404 before the first submit.

## Voice agent (backend/policy.py, backend/voice_tools.py)

### `GET /sessions/{sessionId}/voice-config`
Response: `{ "systemPrompt": "...", "tools": [ ...function declarations... ], "voiceName": "Zephyr" }`
Register all three with the Gemini Live session. The prompt includes the problem text.
`voiceName` is a Gemini prebuilt voice, set with `VOICE_NAME` in `.env` (default Zephyr).

### `POST /sessions/{sessionId}/tools`
Request: `{ "name": "point_to_region", "args": { "region_id": "code_1", "line": 4 } }`
Executes a voice-agent tool call. Return the response JSON to the model as the tool result.
Only `ask_question`, `point_to_region`, `flag_error_type`, `give_hint` are accepted.
`point_to_region` and `flag_error_type` also push a `highlight` event on the WebSocket.
`give_hint` enforces the hint ladder and may return `ok: false` with an instruction to follow.
Questions that look like code are rejected.

### `POST /sessions/{sessionId}/interjection`
Response: `{ "release": null }` or
`{ "release": { "findingId", "regionId", "line", "tier", "category", "mode": "statement" | "question", "instruction" } }`
Call when the candidate pauses and every few seconds of silence. If `release` is not null,
send `"INTERJECT: " + instruction` to the voice session and request a response. At most one
release at a time; tier 4 (syntax) is never released; `mode: "question"` means low confidence.

### `POST /sessions/{sessionId}/phase`
Request: `{ "phase": "clarifying" | "writing" | "tracing" | "done" }`
Edge-case findings (tier 3) are only released during `tracing` or `done`.

### `POST /sessions/{sessionId}/transcript`
Request: `{ "role": "candidate" | "interviewer", "text": "..." }`. Stored for scoring.

### `POST /sessions/{sessionId}/end`
Response: `{ "ok": true }`

## WebSocket `ws://localhost:8000/sessions/{sessionId}/ws`

### Client -> server

Send frames at ~2 fps. JPEG, longest side about 1280 px.
```json
{ "type": "frame", "capturedAt": "2026-10-17T21:00:00.000Z", "imageData": "data:image/jpeg;base64,..." }
```
This matches `CapturedFrame` in `lib/types.ts`, plus `type`.

### Server -> client

Gate status, sent for every frame received:
```json
{ "type": "gate", "changed": true, "stable": false, "busy": false }
```

Pipeline status:
```json
{ "type": "status", "stage": "transcribing" | "analyzing" | "idle" | "error", "detail": "optional text" }
```

Highlight, sent when the voice agent points at the board:
```json
{ "type": "highlight", "regionId": "code_1", "line": 4 }
```
`line` 0 means the whole region. Draw it over the camera view and the editor line.

Board state, sent twice per pass: once as soon as the transcription returns
(`analysisPending: true`, findings from the previous pass), and again when the analyzer
finishes (`analysisPending: false`, updated findings):
```json
{
  "type": "boardState",
  "pass": 3,
  "updatedAt": "2026-10-17T21:00:05.000Z",
  "analysisPending": false,
  "regions": [
    {
      "id": "code_1",
      "type": "code",
      "bbox": { "x": 0.465, "y": 0.185, "width": 0.325, "height": 0.605 },
      "lines": [
        { "n": 1, "text": "function Palindrome(str) {", "lowConfidenceChars": [], "corrected": false },
        { "n": 4, "text": "comp != target - n", "lowConfidenceChars": [], "corrected": true,
          "transcribedText": "comp = target - n" }
      ]
    }
  ],
  "findings": [
    {
      "id": "f1",
      "regionId": "code_1",
      "line": 4,
      "severity": 2,
      "category": "wrong method",
      "confidence": 0.93,
      "message": "...",
      "status": "new"
    }
  ]
}
```
- `bbox` is normalized 0-1 relative to the frame (multiply by the displayed width/height).
- `corrected: true` means the analyzer saw different characters in the image than the transcriber
  read; `text` is the board as written, `transcribedText` is what the transcriber returned.
  Show `text` in the editor (optionally with a subtle marker).
- `severity` is the tier: 1 approach, 2 logic, 3 edge case, 4 syntax.
- `line` is 0 when a finding is not tied to a line.
- `status`: `new | queued | released | resolved`. Finding `id`s are stable across passes while the same issue persists.
- Finding `message` is for debug views only. Do not show it to the candidate: it may name the fix.
  What the candidate hears is decided by the backend interjection policy (Phase 3).

## Voice WebSocket `ws://localhost:8000/sessions/{sessionId}/voice`

Open after creating the session. Audio only (the voice model never receives camera frames).

### Client -> server
- Binary messages: 16 kHz mono PCM16 little-endian microphone audio, ~40 ms chunks.
- Push-to-talk (only when the server reports `pushToTalk: true`):
  `{ "type": "ptt", "state": "down" | "up" }`

### Server -> client
- Binary messages: 24 kHz mono PCM16 interviewer audio. Play in order.
- `{ "type": "voiceStatus", "state": "connected" | "error", "pushToTalk": false, "detail"?: "..." }`
- `{ "type": "interrupted" }`: the candidate talked over the interviewer; stop playback and drop queued audio.
- `{ "type": "transcript", "role": "candidate" | "interviewer", "text": "..." }` (one per completed turn)
- `{ "type": "highlight", "regionId": "code_1", "line": 4 }` (`line` 0 = whole region)
- `{ "type": "toolCall", "name": "...", "args": {...}, "result": {...} }` (debug)
- `{ "type": "released", "findingId": "f1", "mode": "correction" | "question" }` (debug)

When the policy releases a finding, its `status` becomes `released` in the next `boardState`.
