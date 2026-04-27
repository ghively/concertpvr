import { useState } from "react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { VodProgressBar } from "@/components/VodProgressBar";
import { useRecordings, useStreams } from "@/lib/query";
import type { Recording, RecordingStatus, Stream } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_COLOR: Record<string, "live" | "done" | "failed" | "neutral" | "buffering" | "scheduled"> = {
  recording: "live",
  complete: "done",
  failed: "failed",
  interrupted: "failed",
  vod_queued: "scheduled",
  vod_downloading: "buffering",
  vod_failed: "failed",
};

const ALL_FILTER_STATUSES: Array<{ value: RecordingStatus | "all"; label: string }> = [
  { value: "all", label: "All" },
  { value: "recording", label: "Live" },
  { value: "vod_queued", label: "VOD queued" },
  { value: "vod_downloading", label: "VOD downloading" },
  { value: "complete", label: "Complete" },
  { value: "failed", label: "Failed" },
  { value: "interrupted", label: "Interrupted" },
  { value: "vod_failed", label: "VOD failed" },
];

function fmtDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0
    ? `${h}h ${m}m`
    : m > 0
    ? `${m}m ${sec}s`
    : `${sec}s`;
}

function fmtBytes(n: number): string {
  if (n === 0) return "—";
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MiB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GiB`;
}

export default function RecordingsPage() {
  const { data: recordings, isLoading } = useRecordings();
  const { data: streams } = useStreams();
  const streamMap = new Map<number, Stream>((streams ?? []).map((s) => [s.id, s]));

  const [statusFilter, setStatusFilter] = useState<RecordingStatus | "all">("all");

  const visibleRecordings = (recordings ?? []).filter((r) =>
    statusFilter === "all" ? true : r.status === statusFilter
  );

  // Only show filter chips for statuses that have at least 1 recording
  const presentStatuses = new Set((recordings ?? []).map((r) => r.status));

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Recordings</h2>

      {/* Filter chips */}
      {recordings && recordings.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-4">
          {ALL_FILTER_STATUSES.filter(
            (f) => f.value === "all" || presentStatuses.has(f.value as RecordingStatus)
          ).map((f) => (
            <button
              key={f.value}
              onClick={() => setStatusFilter(f.value as RecordingStatus | "all")}
              className={cn(
                "px-2.5 py-0.5 rounded-full text-[11px] border transition-colors",
                statusFilter === f.value
                  ? "bg-terracotta/20 border-terracotta text-terracotta"
                  : "bg-surface-1 border-border text-ink-dim hover:border-ink-faint",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      )}

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}
      {recordings && recordings.length === 0 && (
        <Card className="text-center py-8 text-ink-dim text-xs">
          No recordings yet. Streams page → Add stream → Start buffer; or Schedule page → New schedule.
        </Card>
      )}
      {recordings && recordings.length > 0 && visibleRecordings.length === 0 && (
        <Card className="text-center py-8 text-ink-dim text-xs">
          No recordings match the selected filter.
        </Card>
      )}
      {visibleRecordings.length > 0 && (
        <div className="space-y-2">
          {visibleRecordings.map((r: Recording) => {
            const stream = streamMap.get(r.stream_id);
            const isVodDownloading = r.status === "vod_downloading";
            return (
              <Link key={r.id} to={`/timeline/${r.id}`}>
                <Card className="flex items-center gap-4 hover:border-ink-faint cursor-pointer">
                  <div className="w-32 flex-shrink-0">
                    <div className="font-mono text-[11px] text-ink-faint">
                      {new Date(r.started_at).toLocaleString(undefined, {
                        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                      })}
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">
                      {stream?.title ?? `Recording #${r.id}`}
                    </div>
                    <div className="text-xs text-ink-dim flex items-center gap-3 mt-0.5">
                      <span>{stream?.channel_name ?? "—"}</span>
                      <span>{fmtDuration(r.duration_s)}</span>
                      <span>{fmtBytes(r.size_bytes)}</span>
                      <Badge color={STATUS_COLOR[r.status] ?? "neutral"}>{r.status}</Badge>
                      {r.is_buffer && <Badge color="buffering">buffer</Badge>}
                    </div>
                    {isVodDownloading && (
                      <div className="mt-2" onClick={(e) => e.preventDefault()}>
                        <VodProgressBar recordingId={r.id} />
                      </div>
                    )}
                  </div>
                  <div className="text-xs text-ink-dim">Open editor →</div>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
