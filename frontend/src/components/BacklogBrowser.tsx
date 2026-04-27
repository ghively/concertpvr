import { useState, useMemo } from "react";
import { useWatcherBacklog, useBacklogStatus, useRefreshBacklog } from "@/lib/query";
import { api } from "@/lib/api";
import type { BacklogItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useQueryClient } from "@tanstack/react-query";
import { watchersKeys } from "@/lib/query";
import { cn } from "@/lib/utils";

type SortMode = "newest" | "longest" | "oldest";

const SORT_LABELS: { value: SortMode; label: string }[] = [
  { value: "newest", label: "Newest" },
  { value: "longest", label: "Longest" },
  { value: "oldest", label: "Oldest" },
];

function fmtDuration(seconds: number | null): string {
  if (seconds === null) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function fmtRelativeDate(iso: string | null): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const days = Math.floor(ms / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "1 day ago";
  if (days < 7) return `${days} days ago`;
  const weeks = Math.floor(days / 7);
  if (weeks === 1) return "1 week ago";
  if (weeks < 5) return `${weeks} weeks ago`;
  const months = Math.floor(days / 30);
  if (months === 1) return "1 month ago";
  return `${months} months ago`;
}

function fmtViews(n: number | null): string {
  if (n === null) return "";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M views`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K views`;
  return `${n} views`;
}

function BacklogCard({
  item,
  selected,
  onToggleSelect,
  onDownload,
  onCancel,
}: {
  item: BacklogItem;
  selected: boolean;
  onToggleSelect: () => void;
  onDownload: () => void;
  onCancel: () => void;
}) {
  const isDownloaded = item.state === "downloaded";
  const isQueued = item.state === "queued";

  return (
    <div className="bg-surface-1 border border-border rounded overflow-hidden flex flex-col">
      {/* Thumbnail */}
      <div className="relative w-full" style={{ paddingBottom: "56.25%" }}>
        {item.thumbnail_url ? (
          <img
            src={item.thumbnail_url}
            alt={item.title}
            className="absolute inset-0 w-full h-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 bg-surface-3" />
        )}
        {/* State badge */}
        {isDownloaded && (
          <span className="absolute top-1.5 right-1.5 bg-surface-0/85 text-sage text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded">
            ✓ Downloaded
          </span>
        )}
        {isQueued && (
          <span className="absolute top-1.5 right-1.5 bg-surface-0/85 text-amber text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded">
            ⋯ Queued
          </span>
        )}
        {/* Duration overlay */}
        {item.duration_s !== null && (
          <span className="absolute bottom-1.5 right-1.5 bg-surface-0/85 text-ink text-[10px] font-mono px-1.5 py-0.5 rounded">
            {fmtDuration(item.duration_s)}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="px-2.5 pt-2 pb-1.5 flex-1">
        <div className="text-[12px] font-medium leading-snug line-clamp-2 mb-1">{item.title}</div>
        <div className="text-[10px] text-ink-dim flex items-center gap-1.5">
          {fmtRelativeDate(item.upload_date)}
          {item.view_count !== null && (
            <>
              <span>·</span>
              <span>{fmtViews(item.view_count)}</span>
            </>
          )}
        </div>
      </div>

      {/* Action bar */}
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-t border-border bg-surface-0">
        {isDownloaded ? (
          <>
            <span className="text-[11px] text-ink-faint">In library</span>
            <span className="flex-1" />
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="text-[11px] border border-border rounded px-2 py-0.5 text-ink hover:border-border-strong transition-colors"
            >
              Open
            </a>
          </>
        ) : isQueued ? (
          <>
            <span className="text-[11px] text-ink-faint">Queued</span>
            <span className="flex-1" />
            <button
              onClick={onCancel}
              className="text-[11px] border border-border rounded px-2 py-0.5 text-ink hover:border-border-strong transition-colors"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            {/* Checkbox */}
            <button
              onClick={onToggleSelect}
              className={cn(
                "w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center text-[11px] transition-colors",
                selected
                  ? "bg-sage border-sage text-surface-0"
                  : "bg-surface-2 border-border-strong text-transparent",
              )}
              aria-label={selected ? "Deselect" : "Select"}
              aria-pressed={selected}
            >
              ✓
            </button>
            <span className="flex-1" />
            <button
              onClick={onDownload}
              className={cn(
                "text-[11px] rounded px-2 py-0.5 font-medium transition-colors",
                selected
                  ? "bg-terracotta border border-terracotta-dim text-white"
                  : "border border-border text-ink hover:border-border-strong",
              )}
            >
              Download
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export function BacklogBrowser({ watcherId }: { watcherId: number }) {
  const [sort, setSort] = useState<SortMode>("newest");
  const [offset, setOffset] = useState(0);
  const [titleFilter, setTitleFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allPages, setAllPages] = useState<BacklogItem[][]>([]);
  const qc = useQueryClient();

  // --- Cache status + polling ---
  const statusQuery = useBacklogStatus(watcherId, false);
  const cacheStatus = statusQuery.data?.status;
  const isPolling = cacheStatus === "fetching";

  // Re-query with polling enabled when fetching
  const statusPollQuery = useBacklogStatus(watcherId, isPolling);
  const cacheState = statusPollQuery.data ?? statusQuery.data;

  // User-triggered only — backlog browse never auto-downloads.
  const refreshMutation = useRefreshBacklog(watcherId);

  const { data, isLoading, isError } = useWatcherBacklog(watcherId, sort, offset, "");

  // When sort changes, reset pagination and clear accumulated pages
  const handleSortChange = (newSort: SortMode) => {
    if (newSort === sort) return;
    setSort(newSort);
    setOffset(0);
    setAllPages([]);
    setSelected(new Set());
  };

  // Collect all items from loaded pages + current page
  const allItems = useMemo(() => {
    const current = data ?? [];
    return [...allPages.flat(), ...current];
  }, [allPages, data]);

  // When "Load 50 more" is clicked, save current page and advance offset
  const handleLoadMore = () => {
    if (data && data.length > 0) {
      setAllPages((prev) => [...prev, data]);
      setOffset((prev) => prev + 50);
    }
  };

  // Client-side title filter (kept for immediate responsiveness alongside server q param)
  const filteredItems = useMemo(() => {
    const q = titleFilter.trim().toLowerCase();
    if (!q) return allItems;
    return allItems.filter((item) => item.title.toLowerCase().includes(q));
  }, [allItems, titleFilter]);

  const toggleSelect = (youtubeId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(youtubeId)) {
        next.delete(youtubeId);
      } else {
        next.add(youtubeId);
      }
      return next;
    });
  };

  // User-triggered only — backlog browse never auto-downloads.
  const handleBulkDownload = async () => {
    if (selected.size === 0) return;
    try {
      await api.post(`/api/channel-watchers/${watcherId}/backlog/download`, {
        video_ids: [...selected],
      });
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: watchersKeys.backlog(watcherId, sort, offset) });
    } catch {
      // silently fail for now — production would show a toast
    }
  };

  const handleSingleDownload = async (youtubeId: string) => {
    try {
      await api.post(`/api/channel-watchers/${watcherId}/backlog/download`, {
        video_ids: [youtubeId],
      });
      qc.invalidateQueries({ queryKey: watchersKeys.backlog(watcherId, sort, offset) });
    } catch {
      // silently fail
    }
  };

  const handleCancelItem = async (youtubeId: string) => {
    try {
      await api.post(`/api/channel-watchers/${watcherId}/backlog/cancel`, {
        video_ids: [youtubeId],
      });
      qc.invalidateQueries({ queryKey: watchersKeys.backlog(watcherId, sort, offset) });
    } catch {
      // silently fail
    }
  };

  const handleRefresh = () => {
    refreshMutation.mutate();
  };

  // --- Cache state machine banners ---

  const renderCacheBanner = () => {
    if (!cacheState) return null;

    if (cacheState.status === "never_fetched") {
      return (
        <div className="bg-surface-1 border border-border rounded px-4 py-5 mb-4 flex flex-col items-center gap-3 text-center">
          <p className="text-[13px] text-ink font-medium">
            We haven't browsed this channel yet — click 'Refresh' to fetch the full upload list.
          </p>
          <p className="text-[11px] text-ink-faint">
            Takes ~30s for large channels.
          </p>
          <Button
            variant="primary"
            onClick={handleRefresh}
            disabled={refreshMutation.isPending}
          >
            {refreshMutation.isPending ? "Starting…" : "Refresh"}
          </Button>
        </div>
      );
    }

    if (cacheState.status === "fetching") {
      return (
        <div className="bg-surface-1 border border-border rounded px-4 py-4 mb-4 flex items-center gap-3">
          {/* Spinner */}
          <svg
            className="w-4 h-4 animate-spin text-ink-dim flex-shrink-0"
            viewBox="0 0 24 24"
            fill="none"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z"
            />
          </svg>
          <span className="text-[12px] text-ink flex-1">Fetching channel videos…</span>
          {cacheState.progress_pct > 0 && (
            <span className="text-[11px] text-ink-faint">{cacheState.progress_pct}%</span>
          )}
          <Button variant="default" disabled>
            Refresh
          </Button>
        </div>
      );
    }

    if (cacheState.status === "error") {
      return (
        <div className="bg-surface-1 border border-red-500/40 rounded px-4 py-4 mb-4 flex items-center gap-3">
          <span className="text-[12px] text-red-400 flex-1">
            {cacheState.error ?? "An error occurred while fetching the channel backlog."}
          </span>
          <Button
            variant="default"
            onClick={handleRefresh}
            disabled={refreshMutation.isPending}
          >
            {refreshMutation.isPending ? "Retrying…" : "Retry"}
          </Button>
        </div>
      );
    }

    if (cacheState.status === "complete") {
      return (
        <div className="flex items-center gap-2 mb-3 text-[11px] text-ink-faint">
          <span>Last updated {fmtRelativeDate(cacheState.fetched_at)}</span>
          {cacheState.total_count > 0 && (
            <span className="text-ink-dim">· {cacheState.total_count.toLocaleString()} videos</span>
          )}
          <span className="flex-1" />
          {cacheState.stale && (
            <span className="text-amber text-[10px]">Stale — refresh recommended</span>
          )}
          <button
            onClick={handleRefresh}
            disabled={refreshMutation.isPending}
            className={cn(
              "border rounded px-2.5 py-0.5 text-[11px] transition-colors",
              cacheState.stale
                ? "border-amber/60 text-amber hover:border-amber"
                : "border-border text-ink-dim hover:border-border-strong hover:text-ink",
              refreshMutation.isPending && "opacity-50 cursor-not-allowed",
            )}
          >
            {refreshMutation.isPending ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      );
    }

    return null;
  };

  return (
    <div>
      {/* Bulk-download bar (sticky) — User-triggered only — backlog browse never auto-downloads. */}
      {selected.size > 0 && (
        <div className="sticky top-0 z-10 bg-surface-1 border border-border rounded px-3 py-2 flex items-center gap-2 mb-3 shadow-md">
          <span className="w-4 h-4 rounded border border-sage bg-sage flex items-center justify-center text-surface-0 text-[11px]">
            ✓
          </span>
          <span className="text-[12px]">{selected.size} selected</span>
          <span className="flex-1" />
          <Button variant="primary" onClick={handleBulkDownload}>
            Queue {selected.size} download{selected.size !== 1 ? "s" : ""}
          </Button>
          <Button variant="default" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      )}

      {/* Cache status banner */}
      {renderCacheBanner()}

      {/* Toolbar — only show when we have or can show items */}
      {cacheState?.status !== "never_fetched" && (
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <Input
            placeholder="Filter by title…"
            className="max-w-xs"
            value={titleFilter}
            onChange={(e) => setTitleFilter(e.target.value)}
          />
          <span className="flex-1" />
          <span className="text-[11px] text-ink-faint">Sort:</span>
          <div className="flex gap-1">
            {SORT_LABELS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => handleSortChange(value)}
                className={cn(
                  "px-2.5 py-1 rounded-full text-[11px] border transition-colors",
                  sort === value
                    ? "bg-surface-2 border-border-strong text-ink"
                    : "bg-surface-1 border-border text-ink-dim hover:border-border-strong",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Grid — shown when complete (or during fetching if partial data exists) */}
      {cacheState?.status === "complete" && (
        <>
          {isLoading && allItems.length === 0 && (
            <p className="text-ink-dim text-xs py-8 text-center">Loading backlog…</p>
          )}
          {isError && (
            <p className="text-red-400 text-xs py-8 text-center">
              Failed to load backlog.
            </p>
          )}
          {!isLoading && !isError && filteredItems.length === 0 && (
            <p className="text-ink-dim text-xs py-8 text-center">No videos found.</p>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {filteredItems.map((item) => (
              <BacklogCard
                key={item.youtube_id}
                item={item}
                selected={selected.has(item.youtube_id)}
                onToggleSelect={() => toggleSelect(item.youtube_id)}
                onDownload={() => handleSingleDownload(item.youtube_id)}
                onCancel={() => handleCancelItem(item.youtube_id)}
              />
            ))}
          </div>

          {/* Load more */}
          {data && data.length >= 50 && (
            <div className="text-center mt-4">
              <Button variant="default" onClick={handleLoadMore} disabled={isLoading}>
                {isLoading ? "Loading…" : "Load 50 more"}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
