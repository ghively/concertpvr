import { useState, useMemo } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PosterCard } from "@/components/PosterCard";
import {
  usePublishedSegments,
  useFailedSegments,
  useBulkPublish,
} from "@/lib/query";
import { COMMON_GENRES } from "@/lib/genres";
import type { Segment } from "@/lib/api";

// ── Year helpers ──────────────────────────────────────────────────────────────

const YEAR_OPTIONS = ["All", "2025", "2024", "2023", "Earlier"] as const;
type YearFilter = (typeof YEAR_OPTIONS)[number];

function segmentYear(seg: Segment): number | null {
  if (seg.original_upload_date) {
    const y = parseInt(seg.original_upload_date.substring(0, 4), 10);
    if (!isNaN(y)) return y;
  }
  return null;
}

function matchesYear(seg: Segment, yearFilter: YearFilter): boolean {
  if (yearFilter === "All") return true;
  const y = segmentYear(seg);
  if (y === null) return yearFilter === "Earlier";
  if (yearFilter === "Earlier") return y < 2023;
  return y === Number(yearFilter);
}

// ── Genre helpers ─────────────────────────────────────────────────────────────

function segmentGenres(seg: Segment): string[] {
  if (!seg.genres) return [];
  return seg.genres
    .split(",")
    .map((g) => g.trim())
    .filter(Boolean);
}

function matchesGenres(seg: Segment, selectedGenres: Set<string>): boolean {
  if (selectedGenres.size === 0) return true;
  const genres = segmentGenres(seg);
  // AND logic: every selected genre must be present
  for (const g of selectedGenres) {
    if (!genres.includes(g)) return false;
  }
  return true;
}

// ── Filter chip ───────────────────────────────────────────────────────────────

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
        active
          ? "border-terracotta bg-terracotta/15 text-terracotta"
          : "border-border text-ink-dim hover:border-ink-faint hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

// ── Library page ──────────────────────────────────────────────────────────────

export default function LibraryPage() {
  const { data, isLoading } = usePublishedSegments();
  const { data: failed } = useFailedSegments();
  const bulkPublish = useBulkPublish();
  const [textFilter, setTextFilter] = useState("");
  const [yearFilter, setYearFilter] = useState<YearFilter>("All");
  const [selectedGenres, setSelectedGenres] = useState<Set<string>>(new Set());
  const [retrySummary, setRetrySummary] = useState<{ succeeded: number; failed: number } | null>(
    null,
  );

  const genreOptions = useMemo(() => Array.from(new Set(COMMON_GENRES)).sort(), []);

  const handleBulkRetry = async () => {
    if (!failed || failed.length === 0) return;
    const res = await bulkPublish.mutateAsync(failed.map((s) => s.id));
    setRetrySummary({ succeeded: res.succeeded, failed: res.failed });
  };

  const visible = useMemo(() => {
    return (data ?? []).filter((seg) => {
      // Text filter
      if (textFilter.trim()) {
        const q = textFilter.toLowerCase();
        if (
          !seg.artist.toLowerCase().includes(q) &&
          !(seg.title ?? "").toLowerCase().includes(q)
        ) {
          return false;
        }
      }
      // Year filter
      if (!matchesYear(seg, yearFilter)) return false;
      // Genre filter (AND)
      if (!matchesGenres(seg, selectedGenres)) return false;
      return true;
    });
  }, [data, textFilter, yearFilter, selectedGenres]);

  const toggleGenre = (g: string) => {
    setSelectedGenres((prev) => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g);
      else next.add(g);
      return next;
    });
  };

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Library</h2>
        <span className="flex-1" />
        <Input
          className="max-w-sm"
          placeholder="Filter by artist or title…"
          value={textFilter}
          onChange={(e) => setTextFilter(e.target.value)}
        />
      </div>

      {failed && failed.length > 0 && (
        <Card className="mb-4 border-amber/40 bg-amber/5">
          <div className="flex items-start gap-3">
            <div className="flex-1">
              <div className="text-sm font-medium text-amber">
                {failed.length} segment{failed.length === 1 ? "" : "s"} failed to publish
              </div>
              <div className="text-xs text-ink-dim mt-1">
                Most often a transient ffmpeg or Emby reachability issue. Bulk-retry will
                attempt each segment again with default options.
              </div>
              {retrySummary && (
                <div className="text-xs mt-2">
                  Retry result:{" "}
                  <span className="text-sage">{retrySummary.succeeded} published</span>
                  {retrySummary.failed > 0 && (
                    <>
                      , <span className="text-red-400">{retrySummary.failed} still failed</span>
                    </>
                  )}
                </div>
              )}
            </div>
            <Button
              variant="default"
              onClick={handleBulkRetry}
              disabled={bulkPublish.isPending}
            >
              {bulkPublish.isPending ? "Retrying…" : `Retry ${failed.length}`}
            </Button>
          </div>
        </Card>
      )}

      {/* Year filter row */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider text-ink-faint mr-1 select-none">Year:</span>
        {YEAR_OPTIONS.map((y) => (
          <Chip key={y} active={yearFilter === y} onClick={() => setYearFilter(y)}>
            {y}
          </Chip>
        ))}
      </div>

      {/* Genre filter row (multi-select) */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider text-ink-faint mr-1 select-none">Genre:</span>
        {genreOptions.map((g) => (
          <Chip key={g} active={selectedGenres.has(g)} onClick={() => toggleGenre(g)}>
            {g}
          </Chip>
        ))}
        {selectedGenres.size > 0 && (
          <button
            className="text-[11px] text-ink-faint hover:text-ink ml-1"
            onClick={() => setSelectedGenres(new Set())}
          >
            Clear
          </button>
        )}
      </div>

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}
      {!isLoading && visible.length === 0 && (
        <Card className="text-center py-8 text-ink-dim text-xs">
          No published segments yet. Open a recording in the Timeline editor to publish one.
        </Card>
      )}
      <div className="grid grid-cols-5 gap-4">
        {visible.map((seg) => (
          <PosterCard key={seg.id} segment={seg} />
        ))}
      </div>
    </div>
  );
}
