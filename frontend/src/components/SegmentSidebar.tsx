import type { Segment } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirm } from "@/components/ui/confirm";
import { cn } from "@/lib/utils";

const STATUS_COLOR = {
  draft: "neutral",
  publishing: "buffering",
  published: "done",
  publish_failed: "failed",
} as const;

function fmt(s: number): string {
  const sec = Math.max(0, Math.floor(s));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const r = sec % 60;
  return h > 0
    ? `${h}:${m.toString().padStart(2, "0")}:${r.toString().padStart(2, "0")}`
    : `${m}:${r.toString().padStart(2, "0")}`;
}

interface Props {
  segments: Segment[];
  selectedSegmentId: number | null;
  onSelect: (id: number) => void;
  onUpdate: (id: number, patch: { artist?: string; title?: string | null }) => void;
  onDelete: (id: number) => void;
  onPublish: (id: number) => void;
  publishingId: number | null;
  savingId: number | null;
}

export function SegmentSidebar({
  segments,
  selectedSegmentId,
  onSelect,
  onUpdate,
  onDelete,
  onPublish,
  publishingId,
  savingId,
}: Props) {
  const confirm = useConfirm();

  if (segments.length === 0) {
    return (
      <Card className="text-center py-8 text-ink-dim text-xs">
        No segments yet. Drag on the timeline below to create one, or paste a setlist.
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      {segments.map((seg) => {
        const isSelected = seg.id === selectedSegmentId;
        const isPublishing = publishingId === seg.id;
        const isSaving = savingId === seg.id;
        return (
          <Card
            key={seg.id}
            className={cn("cursor-pointer", isSelected && "ring-2 ring-terracotta")}
            onClick={() => onSelect(seg.id)}
          >
            <div className="flex items-center gap-2 mb-2">
              <Input
                value={seg.artist}
                onChange={(e) => onUpdate(seg.id, { artist: e.target.value })}
                className="font-medium text-sm flex-1"
                onClick={(e) => e.stopPropagation()}
              />
              <Badge color={STATUS_COLOR[seg.status]}>{seg.status}</Badge>
              {isSaving && (
                <span className="text-[10px] text-amber animate-pulse">saving…</span>
              )}
            </div>
            <Input
              value={seg.title ?? ""}
              placeholder="Title (optional)"
              onChange={(e) => onUpdate(seg.id, { title: e.target.value || null })}
              className="text-xs mb-2"
              onClick={(e) => e.stopPropagation()}
            />
            <div className="flex items-center text-[11px] font-mono text-ink-dim">
              <span className="text-amber">{fmt(seg.start_s)} → {fmt(seg.end_s)}</span>
              <span className="ml-2 text-ink-faint">({fmt(seg.end_s - seg.start_s)})</span>
              <span className="ml-2 text-ink-faint">{seg.source}</span>
            </div>
            {seg.error && (
              <div className="text-[11px] text-red-400 mt-1">{seg.error}</div>
            )}
            <div className="flex gap-1 mt-2">
              {seg.status === "draft" && (
                <Button
                  variant="primary"
                  onClick={(e) => { e.stopPropagation(); onPublish(seg.id); }}
                  disabled={isPublishing}
                >
                  {isPublishing ? "Publishing…" : "Publish"}
                </Button>
              )}
              {seg.status === "publish_failed" && (
                <Button
                  onClick={(e) => { e.stopPropagation(); onPublish(seg.id); }}
                  disabled={isPublishing}
                >
                  Retry
                </Button>
              )}
              <Button
                variant="ghost"
                onClick={async (e) => {
                  e.stopPropagation();
                  const ok = await confirm({
                    message: `Delete segment "${seg.artist}"?`,
                    confirmLabel: "Delete",
                    destructive: true,
                  });
                  if (ok) onDelete(seg.id);
                }}
              >
                ✕
              </Button>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
