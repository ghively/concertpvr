import { useState, useRef } from "react";
import type { Segment } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirm } from "@/components/ui/confirm";
import { cn } from "@/lib/utils";
import { COMMON_GENRES } from "@/lib/genres";

// Segment statuses are different than recording statuses
const SEGMENT_STATUS_COLOR = {
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
  onUpdate: (id: number, patch: { artist?: string; title?: string | null; genres?: string | null }) => void;
  onDelete: (id: number) => void;
  onPublish: (id: number) => void;
  publishingId: number | null;
  savingId: number | null;
  /** Tags from the parent stream for click-to-add genre suggestions */
  youtubeTags?: string[] | null;
}

/** Autocomplete-enabled genres input. */
function GenresInput({
  value,
  onChange,
  youtubeTags,
}: {
  value: string;
  onChange: (v: string) => void;
  youtubeTags?: string[] | null;
}) {
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const currentGenres = value
    ? value.split(",").map((g) => g.trim()).filter(Boolean)
    : [];

  const lastToken = value.split(",").pop()?.trim() ?? "";

  const suggestions = lastToken.length > 0
    ? COMMON_GENRES.filter(
        (g) =>
          g.toLowerCase().startsWith(lastToken.toLowerCase()) &&
          !currentGenres.includes(g),
      )
    : [];

  const addGenre = (genre: string) => {
    const parts = value.split(",").map((g) => g.trim()).filter(Boolean);
    // replace last token if it's a partial match, else append
    if (lastToken) {
      parts[parts.length - 1] = genre;
    } else {
      parts.push(genre);
    }
    onChange(parts.join(", "));
    setShowSuggestions(false);
    inputRef.current?.focus();
  };

  const addTag = (tag: string) => {
    const parts = value.split(",").map((g) => g.trim()).filter(Boolean);
    if (!parts.includes(tag)) {
      parts.push(tag);
      onChange(parts.join(", "));
    }
  };

  return (
    <div className="relative mb-2">
      <div className="relative">
        <Input
          ref={inputRef}
          value={value}
          placeholder="Genres (comma-separated)"
          onChange={(e) => { onChange(e.target.value); setShowSuggestions(true); }}
          onFocus={() => setShowSuggestions(true)}
          onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
          className="text-xs"
          onClick={(e) => e.stopPropagation()}
        />
        {showSuggestions && suggestions.length > 0 && (
          <div className="absolute z-20 mt-0.5 w-full rounded border border-border bg-surface-1 shadow-md max-h-32 overflow-auto">
            {suggestions.map((s) => (
              <button
                key={s}
                className="block w-full text-left px-2 py-1 text-xs hover:bg-surface-3 text-ink"
                onMouseDown={(e) => { e.preventDefault(); addGenre(s); }}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
      {youtubeTags && youtubeTags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {youtubeTags.slice(0, 12).map((tag) => {
            const already = currentGenres.includes(tag);
            return (
              <button
                key={tag}
                disabled={already}
                onClick={(e) => { e.stopPropagation(); addTag(tag); }}
                className={cn(
                  "px-1.5 py-0.5 rounded text-[10px] border transition-colors",
                  already
                    ? "border-border text-ink-faint cursor-default"
                    : "border-border hover:border-terracotta text-ink-dim hover:text-terracotta cursor-pointer",
                )}
              >
                {tag}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
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
  youtubeTags,
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
              <Badge color={SEGMENT_STATUS_COLOR[seg.status]}>{seg.status}</Badge>
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
            <GenresInput
              value={seg.genres ?? ""}
              onChange={(v) => onUpdate(seg.id, { genres: v || null })}
              youtubeTags={youtubeTags}
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
