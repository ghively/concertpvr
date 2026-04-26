import { useEffect, useRef, useState } from "react";
import type { Segment } from "@/lib/api";
import { cn } from "@/lib/utils";

const REGION_COLORS = [
  "bg-terracotta/30 border-terracotta",
  "bg-sage/30 border-sage",
  "bg-amber/30 border-amber",
  "bg-mauve/30 border-mauve",
];

function fmtTime(s: number): string {
  const sec = Math.max(0, Math.floor(s));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const r = sec % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${r.toString().padStart(2, "0")}`;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

interface Props {
  durationS: number;
  currentTimeS: number;
  segments: Segment[];
  selectedSegmentId: number | null;
  onSeek: (s: number) => void;
  onSelectSegment: (id: number | null) => void;
  onSegmentDrag: (id: number, startS: number, endS: number) => void;
  onCreate: (startS: number, endS: number) => void;
}

type DragState =
  | { kind: "none" }
  | { kind: "move"; segmentId: number; pxAtStart: number; segStart: number; segEnd: number }
  | { kind: "resize-left"; segmentId: number; segEnd: number }
  | { kind: "resize-right"; segmentId: number; segStart: number }
  | { kind: "create"; pxAtStart: number; pxNow: number };

export function SegmentTimeline({
  durationS,
  currentTimeS,
  segments,
  selectedSegmentId,
  onSeek,
  onSelectSegment,
  onSegmentDrag,
  onCreate,
}: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<DragState>({ kind: "none" });
  const [trackW, setTrackW] = useState(0);

  useEffect(() => {
    if (!trackRef.current) return;
    const obs = new ResizeObserver((entries) => {
      for (const e of entries) setTrackW(e.contentRect.width);
    });
    obs.observe(trackRef.current);
    return () => obs.disconnect();
  }, []);

  const sToPx = (s: number) => (durationS > 0 ? (s / durationS) * trackW : 0);
  const pxToS = (px: number) => (trackW > 0 ? (px / trackW) * durationS : 0);

  const onMouseDownTrack = (e: React.MouseEvent) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    const px = e.clientX - rect.left;
    if (e.detail === 2) {
      onSeek(pxToS(px));
      return;
    }
    setDrag({ kind: "create", pxAtStart: px, pxNow: px });
  };

  useEffect(() => {
    if (drag.kind === "none") return;
    const move = (e: MouseEvent) => {
      if (!trackRef.current) return;
      const rect = trackRef.current.getBoundingClientRect();
      const px = Math.max(0, Math.min(trackW, e.clientX - rect.left));
      switch (drag.kind) {
        case "create":
          setDrag({ ...drag, pxNow: px });
          break;
        case "move": {
          const dx = px - drag.pxAtStart;
          const dS = pxToS(dx);
          const newStart = Math.max(0, drag.segStart + dS);
          const newEnd = Math.min(durationS, drag.segEnd + dS);
          if (Math.abs((newEnd - newStart) - (drag.segEnd - drag.segStart)) < 0.5) {
            onSegmentDrag(drag.segmentId, Math.round(newStart), Math.round(newEnd));
          }
          break;
        }
        case "resize-left": {
          const newStart = Math.max(0, Math.min(drag.segEnd - 1, pxToS(px)));
          onSegmentDrag(drag.segmentId, Math.round(newStart), drag.segEnd);
          break;
        }
        case "resize-right": {
          const newEnd = Math.max(drag.segStart + 1, Math.min(durationS, pxToS(px)));
          onSegmentDrag(drag.segmentId, drag.segStart, Math.round(newEnd));
          break;
        }
      }
    };
    const up = (e: MouseEvent) => {
      if (drag.kind === "create" && trackRef.current) {
        const rect = trackRef.current.getBoundingClientRect();
        const endPx = Math.max(0, Math.min(trackW, e.clientX - rect.left));
        const startS = Math.round(pxToS(Math.min(drag.pxAtStart, endPx)));
        const endS = Math.round(pxToS(Math.max(drag.pxAtStart, endPx)));
        if (Math.abs(endPx - drag.pxAtStart) < 5) {
          onSeek(startS);
        } else if (endS > startS + 1) {
          onCreate(startS, endS);
        }
      }
      setDrag({ kind: "none" });
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, durationS, trackW]);

  if (durationS <= 0) {
    return <div className="text-ink-dim text-xs py-4">Loading timeline…</div>;
  }

  return (
    <div className="select-none">
      <div className="flex justify-between text-[10px] text-ink-faint font-mono mb-1 px-1">
        <span>0:00</span>
        <span>{fmtTime(durationS / 4)}</span>
        <span>{fmtTime(durationS / 2)}</span>
        <span>{fmtTime((durationS * 3) / 4)}</span>
        <span>{fmtTime(durationS)}</span>
      </div>

      <div
        ref={trackRef}
        className="relative h-16 rounded bg-surface-0 border border-border cursor-crosshair"
        onMouseDown={onMouseDownTrack}
      >
        {segments.map((seg, i) => {
          const left = sToPx(seg.start_s);
          const width = sToPx(seg.end_s) - left;
          const color = REGION_COLORS[i % REGION_COLORS.length];
          const isSelected = seg.id === selectedSegmentId;
          return (
            <div
              key={seg.id}
              className={cn(
                "absolute top-1 bottom-1 rounded border-2 flex items-center px-2 cursor-grab",
                color,
                isSelected && "ring-2 ring-ink",
              )}
              style={{ left, width: Math.max(width, 4) }}
              onMouseDown={(e) => {
                e.stopPropagation();
                onSelectSegment(seg.id);
                if (!trackRef.current) return;
                const rect = trackRef.current.getBoundingClientRect();
                setDrag({
                  kind: "move",
                  segmentId: seg.id,
                  pxAtStart: e.clientX - rect.left,
                  segStart: seg.start_s,
                  segEnd: seg.end_s,
                });
              }}
            >
              <div
                className="absolute left-0 top-0 bottom-0 w-1.5 cursor-ew-resize bg-ink/30 hover:bg-ink/60"
                onMouseDown={(e) => {
                  e.stopPropagation();
                  onSelectSegment(seg.id);
                  setDrag({ kind: "resize-left", segmentId: seg.id, segEnd: seg.end_s });
                }}
              />
              <div
                className="absolute right-0 top-0 bottom-0 w-1.5 cursor-ew-resize bg-ink/30 hover:bg-ink/60"
                onMouseDown={(e) => {
                  e.stopPropagation();
                  onSelectSegment(seg.id);
                  setDrag({ kind: "resize-right", segmentId: seg.id, segStart: seg.start_s });
                }}
              />
              {width > 60 && (
                <span className="text-[10px] font-medium truncate text-ink mx-2">
                  {seg.artist}
                </span>
              )}
            </div>
          );
        })}

        {drag.kind === "create" && (
          <div
            className="absolute top-1 bottom-1 rounded border-2 border-dashed border-ink-faint bg-ink/10 pointer-events-none"
            style={{
              left: Math.min(drag.pxAtStart, drag.pxNow),
              width: Math.abs(drag.pxNow - drag.pxAtStart),
            }}
          />
        )}

        <div
          className="absolute top-0 bottom-0 w-0.5 bg-red-500 pointer-events-none"
          style={{ left: sToPx(currentTimeS) }}
        >
          <div className="absolute -top-1 -left-1.5 w-3 h-2 bg-red-500 rounded-sm" />
        </div>
      </div>

      <div className="text-[10px] text-ink-faint mt-1 font-mono">
        Drag empty space to create a segment · drag region body to slide · drag handles to resize · double-click to seek
      </div>
    </div>
  );
}
