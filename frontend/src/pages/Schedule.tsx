import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useSchedules, useDeleteSchedule } from "@/lib/query";
import { NewScheduleDialog } from "@/components/NewScheduleDialog";
import { ScheduleGrid } from "@/components/ScheduleGrid";
import type { Schedule } from "@/lib/api";

export default function SchedulePage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selected, setSelected] = useState<Schedule | null>(null);
  const { data, isLoading } = useSchedules();
  const del = useDeleteSchedule();

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Schedule</h2>
        <span className="flex-1" />
        <Button variant="primary" onClick={() => setDialogOpen(true)}>
          ＋ New schedule
        </Button>
      </div>

      <NewScheduleDialog open={dialogOpen} onOpenChange={setDialogOpen} />

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}

      {data && (
        <ScheduleGrid
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
                onClick={() => {
                  if (confirm("Delete this schedule?")) {
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
