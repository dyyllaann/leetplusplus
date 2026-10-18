"use client";

import type { HighlightEvent, Region } from "@/lib/types";

type Box = { x: number; y: number; width: number; height: number };

/** Box for the highlighted line, or the whole region when line is 0. Uses the line's own
 * bbox when the transcriber provided one, otherwise an even slice of the region. */
export function highlightBox(regions: Region[], highlight: HighlightEvent | null): Box | null {
  if (!highlight) return null;
  const region = regions.find((r) => r.id === highlight.regionId);
  if (!region) return null;
  if (!highlight.line) return region.bbox;
  const index = region.lines.findIndex((l) => l.n === highlight.line);
  if (index < 0) return region.bbox;
  const own = region.lines[index].bbox;
  if (own) return own;
  const h = region.bbox.height / Math.max(region.lines.length, 1);
  return { x: region.bbox.x, y: region.bbox.y + h * index, width: region.bbox.width, height: h };
}

/**
 * Draws the voice agent's current highlight over the camera view. Place it inside the
 * same relatively positioned element as the <video> (it fills that element).
 */
export function HighlightOverlay({ regions, highlight }: { regions: Region[]; highlight: HighlightEvent | null }) {
  const box = highlightBox(regions, highlight);
  if (!box || !highlight) return null;
  const pad = 0.006;
  return (
    <div className="pointer-events-none absolute inset-0" aria-live="polite">
      <div
        className="absolute rounded-sm border-[3px] border-amber-400 bg-amber-300/20 shadow-[0_0_0_4px_rgba(251,191,36,0.25)] motion-safe:animate-pulse"
        style={{
          left: `${(box.x - pad) * 100}%`,
          top: `${(box.y - pad) * 100}%`,
          width: `${(box.width + 2 * pad) * 100}%`,
          height: `${(box.height + 2 * pad) * 100}%`,
        }}
      />
      <span className="sr-only">
        Interviewer is pointing at {highlight.line ? `line ${highlight.line} of ` : ""}
        {highlight.regionId}
      </span>
    </div>
  );
}

/** True when a transcript line should be emphasized because the agent pointed at it. */
export function isHighlightedLine(highlight: HighlightEvent | null, regionId: string, line: number): boolean {
  return !!highlight && highlight.regionId === regionId && (highlight.line === 0 || highlight.line === line);
}
