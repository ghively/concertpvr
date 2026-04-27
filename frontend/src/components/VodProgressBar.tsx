import { useWebSocket } from "@/lib/ws";

type VodProgressMsg = {
  pct: number;
  bytes_total: number | null;
  bitrate_bps: number | null;
  eta_s: number | null;
};

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MiB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GiB`;
}

function fmtBitrate(bps: number): string {
  const kbps = bps / 1000;
  if (kbps < 1000) return `${kbps.toFixed(0)} kbps`;
  return `${(kbps / 1000).toFixed(1)} Mbps`;
}

function fmtEta(etaS: number): string {
  if (etaS < 60) return `${Math.round(etaS)}s`;
  if (etaS < 3600) return `${Math.round(etaS / 60)}m`;
  return `${(etaS / 3600).toFixed(1)}h`;
}

interface VodProgressBarProps {
  recordingId: number;
}

/**
 * Determinate progress bar for VOD downloads. Subscribes to
 * /ws/recordings/{id}/progress and renders pct + ETA + bytes/rate live.
 * Use this for kind=video recordings in vod_downloading state.
 */
export function VodProgressBar({ recordingId }: VodProgressBarProps) {
  const { last, connected } = useWebSocket<VodProgressMsg>(
    `/ws/recordings/${recordingId}/progress`,
  );

  const pct = last?.pct ?? 0;
  const safePct = Math.min(100, Math.max(0, pct));

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px] font-mono text-ink-dim">
        <div className="flex items-center gap-2">
          <span
            className={
              "inline-block h-2 w-2 rounded-full " +
              (connected ? "bg-sage" : "bg-ink-faint")
            }
          />
          <span className="text-sage">{safePct.toFixed(1)}%</span>
          {last?.bitrate_bps != null && last.bitrate_bps > 0 && (
            <span className="text-ink-faint">{fmtBitrate(last.bitrate_bps)}</span>
          )}
          {last?.bytes_total != null && last.bytes_total > 0 && (
            <span className="text-ink-faint">{fmtBytes(last.bytes_total)}</span>
          )}
        </div>
        {last?.eta_s != null && (
          <span className="text-ink-faint">ETA {fmtEta(last.eta_s)}</span>
        )}
      </div>
      <div className="h-1.5 w-full rounded-full bg-surface-3 overflow-hidden">
        <div
          className="h-full rounded-full bg-sage transition-all duration-500"
          style={{ width: `${safePct}%` }}
        />
      </div>
    </div>
  );
}
