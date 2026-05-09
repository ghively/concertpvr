import { useState, useMemo } from "react";
import { Card } from "@/components/ui/card";
import { useRecordings, useStreams } from "@/lib/query";
import { VodQueueStrip } from "@/components/VodQueueStrip";
import { VodRecordingRow } from "@/components/VodRecordingRow";
import type { Recording, Stream } from "@/lib/api";
import { cn } from "@/lib/utils";

type VodFilter = "all" | "queued" | "downloading" | "complete" | "failed";

const FILTER_LABEL: Record<VodFilter, string> = {
  all: "All",
  queued: "Queued",
  downloading: "Downloading",
  complete: "Complete",
  failed: "Failed",
};

const FILTER_STATUSES: Record<VodFilter, string[]> = {
  all: ["vod_queued", "vod_downloading", "complete", "vod_failed"],
  queued: ["vod_queued"],
  downloading: ["vod_downloading"],
  complete: ["complete"],
  failed: ["vod_failed"],
};

export default function VodRecordingsPage() {
  const { data: recordings, isLoading } = useRecordings();
  const { data: streams } = useStreams();
  const [filter, setFilter] = useState<VodFilter>("all");

  const streamMap = useMemo(
    () => new Map<number, Stream>((streams ?? []).map((s) => [s.id, s])),
    [streams],
  );

  const visible = (recordings ?? []).filter((r) => {
    const stream = streamMap.get(r.stream_id);
    if (stream?.kind !== "video") return false; // only VOD-originated
    return FILTER_STATUSES[filter].includes(r.status);
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold">VOD Downloads</h2>
          <p className="text-xs text-ink-dim mt-0.5">
            Videos downloaded from YouTube — separate from live recordings.
          </p>
        </div>
        <VodQueueStrip />
      </div>

      <div className="flex gap-2 mb-4">
        {(Object.keys(FILTER_LABEL) as VodFilter[]).map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={cn(
              "px-3 py-1 rounded-full text-xs border transition-colors",
              filter === k
                ? "bg-surface-2 border-ink-faint text-ink"
                : "border-surface-2 text-ink-dim hover:text-ink",
            )}
          >
            {FILTER_LABEL[k]}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-xs text-ink-dim">Loading…</p>}

      {!isLoading && visible.length === 0 && (
        <Card className="text-center py-8 text-xs text-ink-dim">
          No VOD downloads in this view. Paste a YouTube URL on the Sources page
          to start one.
        </Card>
      )}

      <div className="space-y-3">
        {visible.map((r: Recording) => (
          <VodRecordingRow
            key={r.id}
            recording={r}
            stream={streamMap.get(r.stream_id)}
          />
        ))}
      </div>
    </div>
  );
}
