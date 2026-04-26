export function SetlistDialog({
  recordingId, open, onOpenChange,
}: { recordingId: number; open: boolean; onOpenChange: (o: boolean) => void }) {
  void recordingId;
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center">
      <div className="bg-surface-1 border border-border-strong rounded-lg p-4 text-ink-dim text-xs">
        SetlistDialog stub — implemented in Task 7.
        <button className="ml-2 underline" onClick={() => onOpenChange(false)}>Close</button>
      </div>
    </div>
  );
}
