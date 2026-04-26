import type { Schedule, Stream } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useStreams } from "@/lib/query";

const STATUS_COLOR = {
  pending: "scheduled",
  running: "live",
  complete: "done",
  failed: "failed",
  cancelled: "neutral",
} as const;

function fmtDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit", minute: "2-digit",
  });
}

function groupByDay(schedules: Schedule[]): Map<string, Schedule[]> {
  const out = new Map<string, Schedule[]>();
  for (const sch of schedules) {
    const key = fmtDay(sch.starts_at);
    const arr = out.get(key) ?? [];
    arr.push(sch);
    out.set(key, arr);
  }
  return out;
}

export function ScheduleGrid({
  schedules,
  onClickSchedule,
}: {
  schedules: Schedule[];
  onClickSchedule?: (s: Schedule) => void;
}) {
  const { data: streams } = useStreams();
  const streamMap = new Map<number, Stream>((streams ?? []).map((s) => [s.id, s]));

  if (schedules.length === 0) {
    return (
      <Card className="text-center py-8 text-ink-dim text-xs">
        No schedules yet. Click &ldquo;New schedule&rdquo; to plan a recording.
      </Card>
    );
  }

  const groups = groupByDay(schedules);

  return (
    <div className="space-y-4">
      {[...groups.entries()].map(([day, items]) => (
        <div key={day}>
          <h3 className="text-[11px] uppercase tracking-wider text-ink-faint mb-2">{day}</h3>
          <div className="space-y-2">
            {items.map((sch) => {
              const stream = streamMap.get(sch.stream_id);
              return (
                <Card
                  key={sch.id}
                  className="flex items-center gap-3 cursor-pointer hover:border-ink-faint"
                  onClick={() => onClickSchedule?.(sch)}
                >
                  <span className="font-mono text-xs text-amber w-32">
                    {fmtTime(sch.starts_at)} → {fmtTime(sch.ends_at)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">
                      {sch.artist ?? stream?.title ?? `Schedule #${sch.id}`}
                    </div>
                    <div className="text-xs text-ink-dim truncate">
                      {stream?.channel_name ?? "—"}
                    </div>
                  </div>
                  <Badge color={STATUS_COLOR[sch.status]}>{sch.status}</Badge>
                </Card>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
