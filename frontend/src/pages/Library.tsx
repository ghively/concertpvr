import { useState, useMemo } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PosterCard } from "@/components/PosterCard";
import { usePublishedSegments } from "@/lib/query";
import { COMMON_GENRES } from "@/lib/genres";
import type { Segment } from "@/lib/api";

// ── Year helpers ──────────────────────────────────────────────────────────────

const YEAR_OPTIONS = ["All", "2025", "2024", "2023", "Earlier"] as const;
type YearFilter = (typeof YEAR_OPTIONS)[number];

function segmentYear(seg: Segment): number | null {
  // Try metadata.year if it exists (future extension), then fall back to started_at
  const meta = (seg as Segment & { metadata?: { year?: number } }).metadata;
  if (meta?.year) return meta.year;
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
  const extended = seg as Segment & { genres?: string };
  if (!extended.genres) return [];
  return extended.genres
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
  const [textFilter, setTextFilter] = useState("");
  const [yearFilter, setYearFilter] = useState<YearFilter>("All");
  const [selectedGenres, setSelectedGenres] = useState<Set<string>>(new Set());

  const genreOptions = useMemo(() => Array.from(new Set(COMMON_GENRES)).sort(), []);

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
