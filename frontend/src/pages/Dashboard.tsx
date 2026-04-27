import { useStreams, useRecordings, useSchedules, useSettings } from "@/lib/query";
import { StatStrip } from "@/components/StatStrip";
import { VodQueueStrip } from "@/components/VodQueueStrip";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LiveProgressBar } from "@/components/LiveProgressBar";

function fmtRelative(iso: string): string {
  const target = new Date(iso).getTime();
  const now = Date.now();
  const diffMs = target - now;
  if (diffMs < 0) return "past";
  const min = Math.round(diffMs / 60000);
  if (min < 60) return `in ${min}m`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `in ${hr}h`;
  return `in ${Math.round(hr / 24)}d`;
}

export default function DashboardPage() {
  const { data: streams } = useStreams();
  const { data: recordings } = useRecordings();
  const { data: schedules } = useSchedules();
  const { data: settings } = useSettings();
  const liveMax = settings?.max_concurrent_recordings ?? 4;
  const vodMax = settings?.max_concurrent_vod_downloads ?? 2;

  const recordingNow = (recordings ?? []).filter((r) => r.status === "recording");
  const liveActive = recordingNow.length;
  const vodActive = (recordings ?? []).filter((r) => r.status === "vod_downloading").length;
  const completed = (recordings ?? []).filter((r) => r.status === "complete").length;
  const upcoming = (schedules ?? [])
    .filter((s) => s.status === "pending" && new Date(s.starts_at).getTime() > Date.now())
    .slice(0, 3);

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Dashboard</h2>

      <StatStrip
        items={[
          { label: "Live now", value: `${liveActive}/${liveMax}`, color: "terra" },
          { label: "VODs downloading", value: `${vodActive}/${vodMax}`, color: "sage" },
          { label: "Streams tracked", value: streams?.length ?? 0, color: "amber" },
          { label: "Scheduled", value: upcoming.length, color: "mauve" },
          { label: "Completed", value: completed, color: "sage" },
        ]}
      />

      <div className="mt-2">
        <VodQueueStrip />
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
          <h3 className="text-xs uppercase tracking-wider text-ink-faint mb-2">Live recordings</h3>
          {recordingNow.length === 0 && (
            <Card className="text-center py-6 text-ink-dim text-xs">
              Nothing recording right now.
            </Card>
          )}
          <div className="space-y-2">
            {recordingNow.map((r) => (
              <Card key={r.id} className="flex items-center gap-4">
                <div className="w-24 aspect-video rounded bg-surface-0 flex items-center justify-center">
                  <Badge color="live">live</Badge>
                </div>
                <div className="flex-1">
                  <div className="font-medium">Recording #{r.id}</div>
                  <div className="text-xs text-ink-dim">stream {r.stream_id}</div>
                  <div className="mt-2"><LiveProgressBar streamId={r.stream_id} /></div>
                </div>
              </Card>
            ))}
          </div>
        </div>

        <div>
          <h3 className="text-xs uppercase tracking-wider text-ink-faint mb-2">Up Next</h3>
          {upcoming.length === 0 && (
            <Card className="text-center py-4 text-ink-dim text-xs">No upcoming schedules.</Card>
          )}
          <div className="space-y-2">
            {upcoming.map((sch) => (
              <Card key={sch.id} className="p-3">
                <div className="font-mono text-[11px] text-amber">
                  {fmtRelative(sch.starts_at)}
                </div>
                <div className="text-sm font-medium mt-0.5">
                  {sch.artist ?? `Schedule #${sch.id}`}
                </div>
                <div className="text-[10px] text-ink-faint mt-1">
                  {new Date(sch.starts_at).toLocaleString(undefined, {
                    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                  })}
                </div>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
