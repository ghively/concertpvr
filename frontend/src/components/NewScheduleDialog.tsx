import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useCreateSchedule } from "@/lib/query";
import type { ApiError } from "@/lib/api";

function localToIsoUtc(localDt: string): string {
  const d = new Date(localDt);
  return d.toISOString();
}

export function NewScheduleDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [url, setUrl] = useState("");
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [artist, setArtist] = useState("");
  const create = useCreateSchedule();

  const submit = () => {
    if (!url.trim() || !starts || !ends) return;
    create.mutate(
      {
        url: url.trim(),
        starts_at: localToIsoUtc(starts),
        ends_at: localToIsoUtc(ends),
        artist: artist.trim() || null,
      },
      {
        onSuccess: () => {
          setUrl(""); setStarts(""); setEnds(""); setArtist("");
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>New schedule</DialogHeader>
      <DialogBody className="space-y-3">
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">YouTube URL</label>
          <Input
            autoFocus
            className="font-mono"
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[11px] text-ink-dim block mb-1">Starts</label>
            <Input
              type="datetime-local"
              className="font-mono"
              value={starts}
              onChange={(e) => setStarts(e.target.value)}
            />
          </div>
          <div>
            <label className="text-[11px] text-ink-dim block mb-1">Ends</label>
            <Input
              type="datetime-local"
              className="font-mono"
              value={ends}
              onChange={(e) => setEnds(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label className="text-[11px] text-ink-dim block mb-1">Artist (optional)</label>
          <Input
            placeholder="e.g. Phish"
            value={artist}
            onChange={(e) => setArtist(e.target.value)}
          />
        </div>
        {create.isError && (
          <p className="text-xs text-red-400">
            {(create.error as ApiError).status === 400
              ? "Invalid times — end must be after start, and the URL must be reachable."
              : create.error.message}
          </p>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={create.isPending}>
          {create.isPending ? "Probing…" : "Schedule"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
