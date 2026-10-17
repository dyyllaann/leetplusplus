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
Asks for an analysis pass as soon as the board is stable, skipping the 5 s interval.
Response: `{ "ok": true }`

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

Board state after each completed pass:
```json
{
  "type": "boardState",
  "pass": 3,
  "updatedAt": "2026-10-17T21:00:05.000Z",
  "regions": [
    {
      "id": "code_1",
      "type": "code",
      "bbox": { "x": 0.465, "y": 0.185, "width": 0.325, "height": 0.605 },
      "lines": [ { "n": 1, "text": "function Palindrome(str) {", "lowConfidenceChars": [] } ]
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
- `severity` is the tier: 1 approach, 2 logic, 3 edge case, 4 syntax.
- `line` is 0 when a finding is not tied to a line.
- `status`: `new | queued | released | resolved`. Finding `id`s are stable across passes while the same issue persists.
- Finding `message` is for debug views only. Do not show it to the candidate: it may name the fix.
  What the candidate hears is decided by the backend interjection policy (Phase 3).
