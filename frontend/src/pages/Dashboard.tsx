import { useStreams, useRecordings } from "@/lib/query";
import { StatStrip } from "@/components/StatStrip";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LiveProgressBar } from "@/components/LiveProgressBar";

export default function DashboardPage() {
  const { data: streams } = useStreams();
  const { data: recordings } = useRecordings();

  const recordingNow = (recordings ?? []).filter((r) => r.status === "recording");
  const completed = (recordings ?? []).filter((r) => r.status === "complete").length;

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Dashboard</h2>

      <StatStrip
        items={[
          { label: "Recording now", value: recordingNow.length, color: "terra" },
          { label: "Streams tracked", value: streams?.length ?? 0, color: "amber" },
          { label: "Completed", value: completed, color: "sage" },
          { label: "Watchers", value: 0, color: "mauve" },
        ]}
      />

      <h3 className="text-xs uppercase tracking-wider text-ink-faint mb-2">Live recordings</h3>
      {recordingNow.length === 0 && (
        <Card className="text-center py-6 text-ink-dim text-xs">
          Nothing recording right now. Open <strong>Streams</strong> to start a buffer.
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
  );
}
