import { useMemo, useState } from "react";
import type { Schedule, Stream } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useStreams } from "@/lib/query";
import { cn } from "@/lib/utils";

const STATUS_COLOR = {
  pending: "bg-amber/20 text-amber border-amber/40",
  running: "bg-sage/20 text-sage border-sage/40",
  complete: "bg-surface-2 text-ink-dim border-border",
  failed: "bg-red-500/20 text-red-400 border-red-500/40",
  cancelled: "bg-surface-2 text-ink-faint border-border",
} as const;

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function addMonths(date: Date, n: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + n, 1);
}

function ymd(date: Date): string {
  // local-time YYYY-MM-DD
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function buildCalendarGrid(monthStart: Date): Date[] {
  // 6 rows × 7 columns = 42 cells. Padded by leading/trailing days from
  // adjacent months so the grid is always uniform.
  const firstWeekday = monthStart.getDay(); // 0=Sun
  const gridStart = new Date(monthStart);
  gridStart.setDate(monthStart.getDate() - firstWeekday);
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    return d;
  });
}

function groupByDate(schedules: Schedule[]): Map<string, Schedule[]> {
  const map = new Map<string, Schedule[]>();
  for (const sch of schedules) {
    const key = ymd(new Date(sch.starts_at));
    const arr = map.get(key) ?? [];
    arr.push(sch);
    map.set(key, arr);
  }
  // Sort each day's items by start time
  for (const arr of map.values()) {
    arr.sort(
      (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
    );
  }
  return map;
}

export function ScheduleCalendar({
  schedules,
  onClickSchedule,
}: {
  schedules: Schedule[];
  onClickSchedule?: (s: Schedule) => void;
}) {
  const { data: streams } = useStreams();
  const streamMap = new Map<number, Stream>((streams ?? []).map((s) => [s.id, s]));

  const [cursor, setCursor] = useState<Date>(() => startOfMonth(new Date()));
  const cells = useMemo(() => buildCalendarGrid(cursor), [cursor]);
  const byDate = useMemo(() => groupByDate(schedules), [schedules]);

  const monthLabel = cursor.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });

  const today = ymd(new Date());

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Button variant="ghost" onClick={() => setCursor(addMonths(cursor, -1))}>
          ← Prev
        </Button>
        <span className="font-medium">{monthLabel}</span>
        <Button variant="ghost" onClick={() => setCursor(addMonths(cursor, 1))}>
          Next →
        </Button>
        <span className="flex-1" />
        <Button variant="default" onClick={() => setCursor(startOfMonth(new Date()))}>
          Today
        </Button>
      </div>

      <Card className="p-0 overflow-hidden">
        {/* Weekday header */}
        <div className="grid grid-cols-7 border-b border-border bg-surface-2">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
            <div
              key={d}
              className="px-2 py-1.5 text-[10px] uppercase tracking-wider text-ink-faint"
            >
              {d}
            </div>
          ))}
        </div>

        {/* Day cells */}
        <div className="grid grid-cols-7">
          {cells.map((date, i) => {
            const isCurMonth = date.getMonth() === cursor.getMonth();
            const key = ymd(date);
            const items = byDate.get(key) ?? [];
            const isToday = key === today;
            return (
              <div
                key={i}
                className={cn(
                  "min-h-24 border-b border-r border-border p-1.5 flex flex-col gap-1",
                  !isCurMonth && "bg-surface-0/40",
                  isToday && "bg-terracotta/5",
                )}
              >
                <div
                  className={cn(
                    "text-[11px] font-mono",
                    isCurMonth ? "text-ink-dim" : "text-ink-faint",
                    isToday && "text-terracotta font-bold",
                  )}
                >
                  {date.getDate()}
                </div>
                {items.slice(0, 3).map((sch) => {
                  const stream = streamMap.get(sch.stream_id);
                  return (
                    <button
                      key={sch.id}
                      onClick={() => onClickSchedule?.(sch)}
                      className={cn(
                        "text-left text-[10px] rounded border px-1.5 py-0.5 truncate hover:opacity-80 transition-opacity",
                        STATUS_COLOR[sch.status],
                      )}
                      title={`${sch.artist ?? stream?.title ?? "Schedule"} · ${fmtTime(sch.starts_at)} → ${fmtTime(sch.ends_at)}`}
                    >
                      <span className="font-mono mr-1">{fmtTime(sch.starts_at)}</span>
                      <span>{sch.artist ?? stream?.title ?? `#${sch.id}`}</span>
                    </button>
                  );
                })}
                {items.length > 3 && (
                  <div className="text-[10px] text-ink-faint">+{items.length - 3} more</div>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
