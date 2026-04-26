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

export function LiveProgressBar({ streamId }: { streamId: number }) {
  const { last, connected } = useWebSocket<ProgressMsg>(
    `/ws/streams/${streamId}/progress`,
  );
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
