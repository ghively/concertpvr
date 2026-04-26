import { useState } from "react";
import { useStreams, useDeleteStream, useToggleWatch, useWatchSubscription } from "@/lib/query";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AddStreamDialog } from "@/components/AddStreamDialog";
import { LiveProgressBar } from "@/components/LiveProgressBar";
import type { Stream } from "@/lib/api";

export default function StreamsPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data, isLoading } = useStreams();

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Streams</h2>
        <span className="flex-1" />
        <Button variant="primary" onClick={() => setDialogOpen(true)}>＋ Add stream</Button>
      </div>

      <AddStreamDialog open={dialogOpen} onOpenChange={setDialogOpen} />

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}
      {data && data.length === 0 && (
        <Card className="text-center py-8 text-ink-dim text-xs">
          No streams yet. Click &ldquo;Add stream&rdquo; to register a YouTube URL.
        </Card>
      )}
      {data && data.length > 0 && (
        <div className="space-y-2">
          {data.map((s) => <StreamRow key={s.id} stream={s} />)}
        </div>
      )}
    </div>
  );
}

function StreamRow({ stream }: { stream: Stream }) {
  const { data: sub } = useWatchSubscription(stream.id);
  const toggle = useToggleWatch(stream.id);
  const del = useDeleteStream();
  const enabled = sub?.enabled ?? false;

  return (
    <Card className="flex items-center gap-4">
      <div className="w-24 aspect-video rounded bg-surface-0 overflow-hidden flex-shrink-0">
        {stream.thumbnail_url && (
          <img src={stream.thumbnail_url} alt="" className="w-full h-full object-cover" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{stream.title}</div>
        <div className="text-xs text-ink-dim flex items-center gap-2 mt-0.5">
          <span>{stream.channel_name}</span>
          <Badge color={stream.kind === "live" ? "live" : "neutral"}>{stream.kind}</Badge>
          {enabled && <Badge color="buffering">buffering</Badge>}
        </div>
        {enabled && <div className="mt-2"><LiveProgressBar streamId={stream.id} /></div>}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <Button
          onClick={() => toggle.mutate({ enabled: !enabled })}
          disabled={toggle.isPending}
        >
          {enabled ? "Stop buffer" : "Start buffer"}
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            if (confirm(`Delete "${stream.title}"?`)) del.mutate(stream.id);
          }}
        >
          ✕
        </Button>
      </div>
    </Card>
  );
}
