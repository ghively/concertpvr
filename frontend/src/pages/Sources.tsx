import { useState, useMemo } from "react";
import {
  useStreams,
  useDeleteStream,
  useToggleWatch,
  useWatchSubscription,
  useRecordings,
  useSettings,
  useChannelWatchers,
  useDvrPull,
} from "@/lib/query";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useConfirm } from "@/components/ui/confirm";
import { LiveProgressBar } from "@/components/LiveProgressBar";
import { SmartPasteModal } from "@/components/SmartPasteModal";
import type { Stream, Recording } from "@/lib/api";
import { STATUS_META } from "@/lib/badges";

// ── Kind badge ────────────────────────────────────────────────────────────────

function KindBadge({ kind }: { kind: Stream["kind"] }) {
  if (kind === "live") {
    return (
      <span className="inline-block rounded px-2 py-0.5 text-[10px] uppercase tracking-wider bg-terracotta/15 text-terracotta">
        Live
      </span>
    );
  }
  return (
    <span className="inline-block rounded px-2 py-0.5 text-[10px] uppercase tracking-wider bg-sage/15 text-sage">
      Video
    </span>
  );
}

// ── Status badge from latest recording ───────────────────────────────────────

function StatusBadge({
  stream,
  recordings,
  enabled,
}: {
  stream: Stream;
  recordings: Recording[];
  enabled: boolean;
}) {
  const streamRecs = recordings
    .filter((r) => r.stream_id === stream.id)
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  const latest = streamRecs[0];

  if (stream.kind === "live") {
    if (!enabled) return <Badge color="neutral">Idle</Badge>;
    if (!latest) return <Badge color="buffering">Buffering</Badge>;
    const status = STATUS_META[latest.status];
    return status ? <Badge color={status.color}>{status.label}</Badge> : <Badge color="neutral">{latest.status}</Badge>;
  }

  // video kind
  if (!latest) return <Badge color="scheduled">Queued</Badge>;
  const status = STATUS_META[latest.status];
  if (latest.status === "vod_downloading") {
    const pct =
      latest.size_bytes && latest.duration_s && latest.duration_s > 0
        ? Math.min(100, Math.round((latest.size_bytes / (latest.duration_s * 2_000_000)) * 100))
        : null;
    return (
      <Badge color="buffering">
        {pct !== null ? `Downloading ${pct}%` : "Downloading"}
      </Badge>
    );
  }
  if (status) return <Badge color={status.color}>{status.label}</Badge>;
  return <Badge color="scheduled">Queued</Badge>;
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

// ── Sources page ──────────────────────────────────────────────────────────────

export default function SourcesPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const { data: streams, isLoading } = useStreams();
  const { data: recordings } = useRecordings();
  const { data: settings } = useSettings();
  const { data: watchers } = useChannelWatchers();

  const [kindFilter, setKindFilter] = useState<"all" | "live" | "video">("all");
  const [watcherFilter, setWatcherFilter] = useState<string>("all");

  const activeCount = (recordings ?? []).filter((r) => r.status === "recording").length;
  const max = settings?.max_concurrent_recordings ?? 4;
  const poolFull = activeCount >= max;

  const visible = useMemo(() => {
    let list = streams ?? [];
    if (kindFilter !== "all") {
      list = list.filter((s) => s.kind === kindFilter);
    }
    if (watcherFilter !== "all") {
      list = list.filter((s) => s.channel_name === watcherFilter);
    }
    return list;
  }, [streams, kindFilter, watcherFilter]);

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Sources</h2>
        <span className="flex-1" />
        <Button variant="primary" onClick={() => setModalOpen(true)}>+ Add URL</Button>
      </div>

      <SmartPasteModal open={modalOpen} onOpenChange={setModalOpen} />

      {/* Kind filter row */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider text-ink-faint mr-1 select-none">Kind:</span>
        {(["all", "live", "video"] as const).map((k) => (
          <Chip key={k} active={kindFilter === k} onClick={() => setKindFilter(k)}>
            {k === "all" ? "All" : k === "live" ? "Live" : "Video"}
          </Chip>
        ))}
      </div>

      {/* Watcher filter row */}
      {(watchers ?? []).length > 0 && (
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className="text-[10px] uppercase tracking-wider text-ink-faint mr-1 select-none">Watcher:</span>
          <Chip active={watcherFilter === "all"} onClick={() => setWatcherFilter("all")}>
            All
          </Chip>
          {(watchers ?? []).map((w) => (
            <Chip
              key={w.id}
              active={watcherFilter === w.channel_name}
              onClick={() => setWatcherFilter(w.channel_name)}
            >
              {w.channel_name}
            </Chip>
          ))}
        </div>
      )}

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}
      {!isLoading && visible.length === 0 && (
        <Card className="text-center py-8 text-ink-dim text-xs">
          No sources yet. Click &ldquo;+ Add URL&rdquo; to add a YouTube URL.
        </Card>
      )}
      {visible.length > 0 && (
        <div className="space-y-2">
          {visible.map((s) => (
            <SourceRow
              key={s.id}
              stream={s}
              recordings={recordings ?? []}
              poolFull={poolFull}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Source row ────────────────────────────────────────────────────────────────

function SourceRow({
  stream,
  recordings,
  poolFull,
}: {
  stream: Stream;
  recordings: Recording[];
  poolFull: boolean;
}) {
  const { data: sub } = useWatchSubscription(stream.id);
  const toggle = useToggleWatch(stream.id);
  const del = useDeleteStream();
  const dvrPull = useDvrPull();
  const confirm = useConfirm();
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
        <div className="text-xs text-ink-dim flex items-center gap-2 mt-0.5 flex-wrap">
          <span>{stream.channel_name}</span>
          <KindBadge kind={stream.kind} />
          <StatusBadge stream={stream} recordings={recordings} enabled={enabled} />
        </div>
        {enabled && stream.kind === "live" && (
          <div className="mt-2">
            <LiveProgressBar streamId={stream.id} />
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {stream.kind === "live" && (
          <Button
            onClick={() => toggle.mutate({ enabled: !enabled })}
            disabled={toggle.isPending || (!enabled && poolFull)}
            title={!enabled && poolFull ? "Max concurrent recordings reached" : undefined}
          >
            {enabled ? "Stop buffer" : poolFull ? "Pool full" : "Start buffer"}
          </Button>
        )}
        {stream.kind === "live" && (
          <Button
            variant="default"
            onClick={async () => {
              const ok = await confirm({
                title: "Pull DVR window",
                message:
                  "Capture from the start of YouTube's DVR window? Only works while the broadcast is live and YouTube is providing a DVR window. The result becomes a regular VOD recording.",
                confirmLabel: "Pull",
              });
              if (ok) dvrPull.mutate(stream.id);
            }}
            disabled={dvrPull.isPending}
            title="Pull from the start of YouTube's DVR window"
          >
            {dvrPull.isPending ? "Queueing…" : "Pull DVR"}
          </Button>
        )}
        <Button
          variant="ghost"
          onClick={async () => {
            const ok = await confirm({
              title: "Delete source",
              message: `Delete "${stream.title}"? This will also remove its recordings.`,
              confirmLabel: "Delete",
              destructive: true,
            });
            if (ok) del.mutate(stream.id);
          }}
        >
          ✕
        </Button>
      </div>
    </Card>
  );
}
