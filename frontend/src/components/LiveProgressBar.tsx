import { useWebSocket } from "@/lib/ws";

type ProgressMsg = {
  bytes_total: number;
  bitrate_bps: number;
  duration_s: number;
  fragment_count: number;
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

function fmtDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
}

function fmtEta(etaS: number): string {
  if (etaS < 60) return `${Math.round(etaS)}s`;
  if (etaS < 3600) return `${Math.round(etaS / 60)}m`;
  return `${(etaS / 3600).toFixed(1)}h`;
}

interface LiveProgressBarProps {
  streamId: number;
  mode?: "indeterminate" | "determinate";
  /** 0–100, used when mode === "determinate" */
  pct?: number;
  /** seconds remaining, used when mode === "determinate" */
  eta_s?: number | null;
}

export function LiveProgressBar({ streamId, mode = "indeterminate", pct, eta_s }: LiveProgressBarProps) {
  const { last, connected } = useWebSocket<ProgressMsg>(
    `/ws/streams/${streamId}/progress`,
  );

  if (mode === "determinate") {
    const safePct = Math.min(100, Math.max(0, pct ?? 0));
    return (
      <div className="space-y-1">
        <div className="flex items-center justify-between text-[11px] font-mono text-ink-dim">
          <span className="text-sage">{safePct.toFixed(1)}%</span>
          {eta_s != null && (
            <span className="text-ink-faint">ETA {fmtEta(eta_s)}</span>
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

  return (
    <div className="flex items-center gap-3 text-[11px] font-mono text-ink-dim">
      <span
        className={
          "inline-block h-2 w-2 rounded-full " + (connected ? "bg-sage" : "bg-ink-faint")
        }
      />
      {last ? (
        <>
          <span className="text-amber">{fmtDuration(last.duration_s)}</span>
          <span>{fmtBytes(last.bytes_total)}</span>
          <span>{fmtBitrate(last.bitrate_bps)}</span>
          <span>{last.fragment_count} fragments</span>
        </>
      ) : (
        <span>Waiting for first chunk…</span>
      )}
    </div>
  );
}
