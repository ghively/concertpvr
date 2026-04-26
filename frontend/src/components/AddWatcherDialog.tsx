import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useCreateChannelWatcher } from "@/lib/query";
import type { ApiError } from "@/lib/api";

export function AddWatcherDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [url, setUrl] = useState("");
  const [filter, setFilter] = useState("");
  const [retention, setRetention] = useState(7);
  const create = useCreateChannelWatcher();

  const submit = () => {
    if (!url.trim()) return;
    create.mutate(
      {
        channel_url: url.trim(),
        title_filter: filter.trim() || null,
        retention_days: retention,
      },
      {
        onSuccess: () => {
          setUrl(""); setFilter(""); setRetention(7);
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>Watch a channel</DialogHeader>
      <DialogBody className="space-y-3">
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">Channel URL or handle</label>
          <Input
            autoFocus
            className="font-mono"
            placeholder="https://www.youtube.com/@nprmusic"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">
            Title filter (regex, optional)
          </label>
          <Input
            className="font-mono"
            placeholder="tiny desk|live"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <p className="text-[10px] text-ink-faint mt-1">
            Only auto-record live broadcasts whose title matches. Leave empty to record all.
          </p>
        </div>
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">Retention (days)</label>
          <Input
            type="number"
            min={1}
            max={365}
            className="font-mono"
            value={retention}
            onChange={(e) => setRetention(Number(e.target.value) || 7)}
          />
        </div>
        {create.isError && (
          <p className="text-xs text-red-400">
            {(create.error as ApiError).status === 409
              ? "This channel is already being watched."
              : (create.error as ApiError).status === 400
              ? "Couldn't fetch channel info — check the URL."
              : create.error.message}
          </p>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={create.isPending}>
          {create.isPending ? "Probing channel…" : "Watch"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
