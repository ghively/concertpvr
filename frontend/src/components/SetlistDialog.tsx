import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { setlistsApi } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { segmentsKeys } from "@/lib/query";

const PLACEHOLDER = `Phoebe Bridgers · 00:21–01:34
Goose · 1:51 - 3:42
Rüfüs Du Sol · 3:58–5:18
Tame Impala · 05:31 to 07:05`;

export function SetlistDialog({
  recordingId,
  open,
  onOpenChange,
}: {
  recordingId: number;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();

  const submit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      await setlistsApi.paste(recordingId, text);
      qc.invalidateQueries({ queryKey: segmentsKeys.forRecording(recordingId) });
      qc.invalidateQueries({ queryKey: ["recordings", recordingId, "setlist"] });
      setText("");
      onOpenChange(false);
    } catch (e) {
      const err = e as { status?: number; body?: { detail?: string } };
      setError(err.body?.detail ?? "Failed to parse setlist.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>Paste setlist</DialogHeader>
      <DialogBody>
        <p className="text-xs text-ink-dim mb-3">
          One artist per line, with start–end times relative to the recording start. Times can be{" "}
          <span className="font-mono">m:ss</span> or <span className="font-mono">h:mm:ss</span>.
          Separators: <span className="font-mono">·</span>, <span className="font-mono">-</span>,
          <span className="font-mono"> – </span>, or <span className="font-mono">to</span>.
        </p>
        <textarea
          autoFocus
          rows={10}
          spellCheck={false}
          className="w-full font-mono text-xs rounded border border-border-strong bg-surface-0 p-2 text-ink placeholder:text-ink-faint focus:outline-none focus:border-terracotta"
          placeholder={PLACEHOLDER}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        {error && <p className="text-xs text-red-400 mt-2">{error}</p>}
        <p className="text-[11px] text-ink-faint mt-2">
          Submitting will replace any existing setlist for this recording. Existing draft segments
          are NOT removed — re-derive by deleting them first if needed.
        </p>
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={submitting || !text.trim()}>
          {submitting ? "Parsing…" : "Apply"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
