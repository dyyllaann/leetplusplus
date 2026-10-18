# Whiteboard Practice Coach (DubHacks '26)

A web app that watches a physical whiteboard through a camera, transcribes handwritten
code and diagrams, and runs a real-time voice interviewer that catches logic errors
without giving away solutions. Session results feed a per-skill spaced-repetition schedule.

Deadline: Sun Oct 18, 10:30 AM. Prefer working, demoable code over completeness.

## Stack
- Frontend: Next.js (camera, mic, audio, read-only mirror editor, dashboard)
- Backend: FastAPI (Python)
- Vision: Perceptron `perceptron-mk1.5` (Isaac model IDs are retired; do not use them)
- Voice: Google Gemini Live API (speech-to-speech) via Pipecat's Gemini Live service; audio only, no video
- Logic analysis: behind an interface; model chosen by config (Perceptron, Gemini, or Claude)
- Database: SQLite for the hackathon

## Environment variables
- `PERCEPTRON_API_KEY`
- `GEMINI_API_KEY` (Gemini Live voice; Gemini analyzer if selected)
- `ANTHROPIC_API_KEY` (analyzer candidate / fallback)

## Architecture (data flow)
1. Client captures frames -> backend.
2. Vision loop: homography to a fixed flattened board view -> per-region frame differencing.
3. Every 5 s (or immediately when the candidate stops speaking), send only regions that pass
   all gates: changed, stable for ~1 s, not occluded.
4. Perceptron: layout pass (regions: id, type, bbox) at session start or when a new area is used;
   per-region literal transcription with a strict JSON schema.
5. Analyzer: `analyze(region_crop, prev_region_state, problem) -> {state, findings}`.
6. Interjection policy (plain backend rules, no model) decides what is released to the voice agent.
7. Gemini Live voice agent converses and calls tools; backend executes tools.
8. End of session: scorer produces rubric JSON; scores and schedule are stored.

### Hackathon simplification (agreed Oct 17)
For the demo, steps 2-4 run on the whole frame: no homography, no layout pass, no per-region
gates. A whole-frame gate (changed vs last analyzed + still for ~1 s) triggers one pass:
Perceptron transcribes the full frame (low reasoning) into region JSON, then the analyzer gets
that JSON plus the frame image (the image catches Perceptron's occasional "corrections").
Regions still come from the transcription output. Camera should be on a fixed tripod.
Manual 4-click flattening is the first thing to add back if time allows.
Backend <-> frontend contract: docs/api.md.
Voice: the backend talks to Gemini Live (`gemini-3.8-live`) directly with the google-genai SDK
(backend/voice/bridge.py) instead of Pipecat; browser audio is raw PCM over a FastAPI WebSocket,
because WebRTC/UDP does not pass through the SSH tunnel used in development.

## Invariants (do not violate)
- Transcription is LITERAL. Never correct the candidate's code, syntax, or comparisons.
- The voice agent has no tool that writes code. Allowed tools only:
  `ask_question`, `point_to_region`, `flag_error_type`, `give_hint(level)`.
- `give_hint` levels are enforced by the backend, not the model.
- Severity tiers:
  1 approach -> interrupt early; 2 logic -> interrupt on completed region;
  3 edge case -> ask during trace or at end; 4 syntax -> never interrupt, report only.
- One interruption at a time; highest tier first.
- Findings below the confidence threshold become questions, not corrections.
- The whiteboard is the only input. The editor is a read-only mirror; manual edits are
  transcription corrections only.
- Audio goes only to the voice model. Other models receive the transcript as text.
- The voice model never receives camera frames, even though Gemini Live supports video.
  All board information reaches it as text context from the backend, after the policy.
- Perceptron context is ~36k tokens: send crop + prior region state + short summary, never full history.
- Session history lives in the database, not in model context.

## Conventions
- All model outputs use strict JSON schemas; validate with Pydantic.
- Keep model clients behind small interfaces so models can be swapped by config.
- Log every analyzer request/response to disk for debugging and demo replay.
- Do not add features outside the current phase without asking.

## Build order
0. Validate models on a saved whiteboard photo (fixtures/whiteboard_1.jpg)
1. Vision loop + analyzer
2. Mirror editor
3. Voice agent + interjection policy
4. Scoring + database
5. Dashboard + spaced repetition (seeded demo history)
Phases 0-4 are the minimum demo.

## Fallbacks
- Realtime voice unstable -> push-to-talk.
- Dashboard behind -> static page from seeded data.
