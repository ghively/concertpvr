import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { VodProgressBar } from "@/components/VodProgressBar";
import type { Recording, Stream } from "@/lib/api";
import { useRetryRecording, useDeleteRecordingSource } from "@/lib/query";
import { STATUS_META } from "@/lib/badges";

interface VodRecordingRowProps {
  recording: Recording;
  stream: Stream | undefined;
}

/**
 * Purpose-built row for VOD recordings on /recordings/vod.
 *
 * Action buttons match the VOD lifecycle:
 *  - vod_queued: Cancel (DELETE /recordings/{id}) — TODO if not implemented
 *  - vod_downloading: VodProgressBar with live %
 *  - complete: Open Review → /recordings/:id/review (or Library link if all segments published)
 *  - vod_failed: Retry → POST /recordings/{id}/retry
 */
export function VodRecordingRow({ recording: r, stream: s }: VodRecordingRowProps) {
  const retryMut = useRetryRecording();
  const deleteSourceMut = useDeleteRecordingSource();
  const status = STATUS_META[r.status] ?? { color: "neutral", label: r.status };

  return (
    <Card className="flex items-start gap-4">
      <div className="w-32 flex-shrink-0">
        {s?.thumbnail_url ? (
          <img src={s.thumbnail_url} className="w-full rounded" alt="" />
        ) : (
          <div className="w-full aspect-video bg-surface-2 rounded" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{s?.title ?? `Recording ${r.id}`}</div>
        <div className="text-xs text-ink-dim">{s?.channel_name}</div>
        <div className="mt-2 flex items-center gap-2">
          <Badge color={status.color}>{status.label}</Badge>
          <span className="text-xs text-ink-faint">
            {new Date(r.started_at).toLocaleString()}
          </span>
        </div>

        {r.status === "vod_downloading" && (
          <div className="mt-2">
            <VodProgressBar recordingId={r.id} />
          </div>
        )}

        {r.status === "vod_failed" && r.error && (
          <div className="mt-2 text-xs text-red-400 font-mono">{r.error}</div>
        )}
      </div>

      <div className="flex flex-col gap-2 items-end">
        {r.status === "vod_failed" && (
          <Button onClick={() => retryMut.mutate(r.id)} disabled={retryMut.isPending}>
            Retry
          </Button>
        )}
        {r.status === "complete" && (
          <Link to={`/recordings/${r.id}/review`}>
            <Button>Open Review</Button>
          </Link>
        )}
        {r.status === "complete" && !r.source_deleted && (
          <Button
            variant="default"
            onClick={() => {
              if (window.confirm("Delete source file? Cannot be undone.")) {
                deleteSourceMut.mutate(r.id);
              }
            }}
            disabled={deleteSourceMut.isPending}
          >
            Delete source
          </Button>
        )}
      </div>
    </Card>
  );
}
