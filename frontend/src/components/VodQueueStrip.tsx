// frontend/src/components/VodQueueStrip.tsx
import { useRecordings, useSettings } from "@/lib/query";

/**
 * Small queue-state widget for the VOD download queue.
 * Reused on Dashboard and at the top of /recordings/vod.
 *
 * Renders: "1 downloading · 3 queued · 2 failed (today)"
 */
export function VodQueueStrip() {
  const { data: recordings } = useRecordings();
  const { data: settings } = useSettings();

  const downloading = (recordings ?? []).filter((r) => r.status === "vod_downloading").length;
  const queued = (recordings ?? []).filter((r) => r.status === "vod_queued").length;
  const failed = (recordings ?? []).filter((r) => r.status === "vod_failed").length;
  const cap = settings?.max_concurrent_vod_downloads ?? 2;

  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="text-sage font-mono">
        {downloading}/{cap}
      </span>
      <span className="text-ink-dim">downloading</span>
      <span className="text-ink-faint">·</span>
      <span className="text-amber font-mono">{queued}</span>
      <span className="text-ink-dim">queued</span>
      {failed > 0 && (
        <>
          <span className="text-ink-faint">·</span>
          <span className="text-red-400 font-mono">{failed}</span>
          <span className="text-ink-dim">failed</span>
        </>
      )}
    </div>
  );
}
