import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { useSchedules, useDeleteSchedule } from "@/lib/query";
import { NewScheduleDialog } from "@/components/NewScheduleDialog";
import { ScheduleGrid } from "@/components/ScheduleGrid";
import { ScheduleCalendar } from "@/components/ScheduleCalendar";
import type { Schedule } from "@/lib/api";
import { cn } from "@/lib/utils";

type ViewMode = "list" | "calendar";

const VIEW_KEY = "concertpvr.schedule.view";

function readInitialView(): ViewMode {
  if (typeof window === "undefined") return "list";
  const v = window.localStorage.getItem(VIEW_KEY);
  return v === "calendar" ? "calendar" : "list";
}

export default function SchedulePage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selected, setSelected] = useState<Schedule | null>(null);
  const [view, setView] = useState<ViewMode>(readInitialView);
  const { data, isLoading } = useSchedules();
  const del = useDeleteSchedule();
  const confirm = useConfirm();

  const setViewPersisted = (mode: ViewMode) => {
    setView(mode);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(VIEW_KEY, mode);
    }
  };

  return (
    <div>
      <div className="flex items-center mb-4 gap-2">
        <h2 className="text-lg font-semibold">Schedule</h2>
        <span className="flex-1" />
        <div className="inline-flex rounded border border-border overflow-hidden mr-2">
          <button
            onClick={() => setViewPersisted("list")}
            className={cn(
              "px-2.5 py-1 text-[11px]",
              view === "list"
                ? "bg-surface-2 text-ink"
                : "bg-surface-1 text-ink-dim hover:text-ink",
            )}
          >
            List
          </button>
          <button
            onClick={() => setViewPersisted("calendar")}
            className={cn(
              "px-2.5 py-1 text-[11px] border-l border-border",
              view === "calendar"
                ? "bg-surface-2 text-ink"
                : "bg-surface-1 text-ink-dim hover:text-ink",
            )}
          >
            Calendar
          </button>
        </div>
        <Button variant="primary" onClick={() => setDialogOpen(true)}>
          ＋ New schedule
        </Button>
      </div>

      <NewScheduleDialog open={dialogOpen} onOpenChange={setDialogOpen} />

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}

      {data && view === "list" && (
        <ScheduleGrid
          schedules={data}
          onClickSchedule={(s) => setSelected(s)}
        />
      )}

      {data && view === "calendar" && (
        <ScheduleCalendar
          schedules={data}
          onClickSchedule={(s) => setSelected(s)}
        />
      )}

      {selected && (
        <div className="fixed bottom-4 right-4 bg-surface-1 border border-border-strong rounded-lg p-4 shadow-xl">
          <div className="flex items-center gap-3">
            <div>
              <div className="font-medium">{selected.artist ?? "Schedule"} #{selected.id}</div>
              <div className="text-xs text-ink-dim">{selected.status}</div>
            </div>
            {selected.status === "pending" && (
              <Button
                variant="ghost"
                onClick={async () => {
                  const ok = await confirm({
                    message: "Delete this schedule?",
                    confirmLabel: "Delete",
                    destructive: true,
                  });
                  if (ok) {
                    del.mutate(selected.id);
                    setSelected(null);
                  }
                }}
              >
                Delete
              </Button>
            )}
            <Button variant="ghost" onClick={() => setSelected(null)}>Close</Button>
          </div>
        </div>
      )}
    </div>
  );
}
