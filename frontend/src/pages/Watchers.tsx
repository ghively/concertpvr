import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useConfirm } from "@/components/ui/confirm";
import {
  useChannelWatchers,
  useUpdateChannelWatcher,
  useDeleteChannelWatcher,
} from "@/lib/query";
import { AddWatcherDialog } from "@/components/AddWatcherDialog";
import type { ChannelWatcher } from "@/lib/api";
import { cn } from "@/lib/utils";

function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return "just now";
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h ago`;
  return `${Math.round(ms / 86_400_000)}d ago`;
}

export default function WatchersPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data, isLoading } = useChannelWatchers();
  const update = useUpdateChannelWatcher();
  const del = useDeleteChannelWatcher();
  const confirm = useConfirm();

  const next_poll_in = (() => {
    const lp = (data ?? []).reduce<number | null>((acc, w) => {
      if (!w.last_polled) return acc;
      const t = new Date(w.last_polled).getTime();
      return acc === null || t > acc ? t : acc;
    }, null);
    if (lp === null) return null;
    const elapsed_s = Math.floor((Date.now() - lp) / 1000);
    return Math.max(0, 60 - elapsed_s);
  })();

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Channel Watchers</h2>
        <span className="flex-1" />
        <span className="text-xs text-ink-dim mr-3">
          Polled every 60s
          {next_poll_in !== null && (
            <span className="text-amber font-mono ml-1">· next in {next_poll_in}s</span>
          )}
        </span>
        <Button variant="primary" onClick={() => setDialogOpen(true)}>
          ＋ Watch a channel
        </Button>
      </div>

      <AddWatcherDialog open={dialogOpen} onOpenChange={setDialogOpen} />

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}
      {data && data.length === 0 && (
        <Card className="text-center py-8 text-ink-dim text-xs">
          No watchers yet. Click &ldquo;Watch a channel&rdquo; to add one.
        </Card>
      )}
      <div className="space-y-2">
        {(data ?? []).map((w) => (
          <WatcherRow
            key={w.id}
            watcher={w}
            onToggle={(enabled) => update.mutate({ id: w.id, patch: { enabled } })}
            onDelete={async () => {
              const ok = await confirm({
                message: `Stop watching "${w.channel_name}"?`,
                confirmLabel: "Stop watching",
                destructive: true,
              });
              if (ok) del.mutate(w.id);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function WatcherRow({
  watcher,
  onToggle,
  onDelete,
}: {
  watcher: ChannelWatcher;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  return (
    <Card className="flex items-center gap-4">
      <div className="w-12 h-12 rounded-full bg-surface-3 flex-shrink-0 overflow-hidden">
        {watcher.avatar_url && (
          <img src={watcher.avatar_url} alt="" className="w-full h-full object-cover" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{watcher.channel_name}</div>
        <div className="text-xs text-ink-dim font-mono truncate">
          {watcher.channel_url} · last polled {fmtRelative(watcher.last_polled)}
        </div>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {watcher.title_filter && (
          <span className="text-[11px] font-mono text-amber bg-amber/10 px-2 py-0.5 rounded">
            ~ {watcher.title_filter}
          </span>
        )}
        <span className="text-[11px] font-mono text-ink-faint">
          {watcher.retention_days}d
        </span>
        {!watcher.enabled && <Badge color="neutral">paused</Badge>}
        <button
          onClick={() => onToggle(!watcher.enabled)}
          className={cn(
            "w-9 h-5 rounded-full relative transition-colors",
            watcher.enabled ? "bg-sage/30" : "bg-surface-3",
          )}
          aria-label={watcher.enabled ? "Disable" : "Enable"}
        >
          <span
            className={cn(
              "absolute top-0.5 w-4 h-4 rounded-full transition-all",
              watcher.enabled ? "left-[18px] bg-sage" : "left-0.5 bg-ink-dim",
            )}
          />
        </button>
        <Button variant="ghost" onClick={onDelete}>✕</Button>
      </div>
    </Card>
  );
}
