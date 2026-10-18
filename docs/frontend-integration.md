# Wiring the new session components into the problem page

New, self-contained files (no existing frontend file was changed, so they cannot conflict):
- `lib/useSessionEvents.ts` — read-only WebSocket for `highlight` and `submission` events.
- `app/_components/session/HighlightOverlay.tsx` — draws the voice agent's highlight over the camera.
- `app/_components/session/EditorTab.tsx` — typed-code editor: Copy from board, Submit/Resubmit, Diff view.
- `app/_components/session/DiffView.tsx` — line diff between the board snapshot and the typed code.
- `app/dev/session-ui/page.tsx` — preview with mock data at `/dev/session-ui` (delete when wired in).

Components live under `app/` because Tailwind only scans `./app/**`.

## Steps (in `app/problems/[id]/page.tsx` and `board-panels.tsx`)

1. Listen for events next to the existing board session:
   ```tsx
   import { useSessionEvents } from "@/lib/useSessionEvents";
   const { highlight, submission, setSubmission } = useSessionEvents(sessionId);
   ```
2. Camera highlight: inside `CameraPanel`, in the same `relative` div as the `<video>`, after the
   region boxes (pass `highlight` down as a prop):
   ```tsx
   import { HighlightOverlay } from "@/app/_components/session/HighlightOverlay";
   <HighlightOverlay regions={regions} highlight={highlight} />
   ```
3. Transcript line highlight: in `BoardPanel`, add a class such as `bg-amber-300/30` to a line
   when `isHighlightedLine(highlight, region.id, line.n)` is true.
4. Editor tab: add a third view button ("Editor") next to "Board Transcript" and "Notes" in
   `BoardPanel`, and render:
   ```tsx
   import { EditorTab } from "@/app/_components/session/EditorTab";
   <EditorTab sessionId={sessionId} problemId={problemId} board={board}
              submission={submission} onSubmitted={setSubmission} />
   ```
5. Run `npm run build` and check `/problems/<id>` in light and dark mode.

Rules (CLAUDE.md invariants): the editor never syncs with the board automatically; "Copy from
board" is a one-time copy; the interviewer and analyzer only use the board.
