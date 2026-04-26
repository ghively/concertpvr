import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAddStream } from "@/lib/query";
import { ApiError } from "@/lib/api";

export function AddStreamDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [url, setUrl] = useState("");
  const add = useAddStream();

  const submit = () => {
    if (!url.trim()) return;
    add.mutate(url.trim(), {
      onSuccess: () => {
        setUrl("");
        onOpenChange(false);
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>Add a stream</DialogHeader>
      <DialogBody>
        <p className="text-xs text-ink-dim mb-3">
          Paste a YouTube URL — we&apos;ll fetch the title, channel, and live status.
        </p>
        <Input
          autoFocus
          className="font-mono"
          placeholder="https://www.youtube.com/watch?v=…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
        {add.isError && (
          <p className="mt-2 text-xs text-red-400">
            {(add.error as ApiError).status === 409
              ? "That stream is already in your library."
              : add.error.message}
          </p>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button variant="primary" onClick={submit} disabled={add.isPending}>
          {add.isPending ? "Probing…" : "Add"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
