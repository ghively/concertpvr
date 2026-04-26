import { useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { VideoPlayer, type VideoPlayerHandle } from "@/components/VideoPlayer";
import { SegmentTimeline } from "@/components/SegmentTimeline";
import { SegmentSidebar } from "@/components/SegmentSidebar";
import { SetlistDialog } from "@/components/SetlistDialog";
import {
  useSegments,
  useCreateSegment,
  useUpdateSegment,
  useDeleteSegment,
  usePublishSegment,
} from "@/lib/query";
import { recordingMediaUrl, type Segment } from "@/lib/api";

export default function TimelineEditorPage() {
  const { id } = useParams<{ id: string }>();
  const recordingId = Number(id);

  const playerHandleRef = useRef<VideoPlayerHandle | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [selectedSegmentId, setSelectedSegmentId] = useState<number | null>(null);
  const [setlistOpen, setSetlistOpen] = useState(false);

  const { data: segments = [], isLoading } = useSegments(recordingId);
  const createMut = useCreateSegment(recordingId);
  const updateMut = useUpdateSegment(recordingId);
  const deleteMut = useDeleteSegment(recordingId);
  const publishMut = usePublishSegment(recordingId);

  const savingId = updateMut.isPending ? (updateMut.variables?.id ?? null) : null;

  const [publishingId, setPublishingId] = useState<number | null>(null);
  const [localSegments, setLocalSegments] = useState<Segment[]>([]);
  useEffect(() => setLocalSegments(segments), [segments]);

  const onSegmentDrag = (segId: number, startS: number, endS: number) => {
    setLocalSegments((curr) =>
      curr.map((s) => (s.id === segId ? { ...s, start_s: startS, end_s: endS } : s))
    );
  };

  const flushTimer = useRef<number | null>(null);
  useEffect(() => {
    if (flushTimer.current !== null) window.clearTimeout(flushTimer.current);
    flushTimer.current = window.setTimeout(() => {
      for (const local of localSegments) {
        const server = segments.find((s) => s.id === local.id);
        if (!server) continue;
        if (server.start_s !== local.start_s || server.end_s !== local.end_s) {
          updateMut.mutate({
            id: local.id,
            patch: { start_s: local.start_s, end_s: local.end_s },
          });
        }
      }
    }, 400);
    return () => {
      if (flushTimer.current !== null) window.clearTimeout(flushTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localSegments]);

  const onCreateRange = (startS: number, endS: number) => {
    createMut.mutate(
      {
        recording_id: recordingId,
        artist: "Untitled",
        start_s: startS,
        end_s: endS,
        source: "manual",
      },
      {
        onSuccess: (s) => setSelectedSegmentId(s.id),
      },
    );
  };

  const onPublish = (segId: number) => {
    setPublishingId(segId);
    publishMut.mutate(
      { id: segId, options: {} },
      {
        onSettled: () => setPublishingId(null),
      },
    );
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (selectedSegmentId !== null && (e.key === "i" || e.key === "I")) {
        e.preventDefault();
        const seg = localSegments.find((s) => s.id === selectedSegmentId);
        if (seg) onSegmentDrag(seg.id, Math.round(currentTime), seg.end_s);
      }
      if (selectedSegmentId !== null && (e.key === "o" || e.key === "O")) {
        e.preventDefault();
        const seg = localSegments.find((s) => s.id === selectedSegmentId);
        if (seg) onSegmentDrag(seg.id, seg.start_s, Math.round(currentTime));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedSegmentId, localSegments, currentTime]);

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Timeline editor</h2>
        <Link to="/recordings" className="ml-3 text-xs text-ink-dim hover:text-ink">
          ← Recordings
        </Link>
        <span className="flex-1" />
        <Button onClick={() => setSetlistOpen(true)}>＋ Setlist</Button>
      </div>

      <SetlistDialog
        recordingId={recordingId}
        open={setlistOpen}
        onOpenChange={setSetlistOpen}
      />

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 space-y-4">
          <Card className="p-0 overflow-hidden">
            <VideoPlayer
              src={recordingMediaUrl(recordingId)}
              onTimeUpdate={setCurrentTime}
              onDuration={setDuration}
              onReady={(h) => { playerHandleRef.current = h; }}
            />
          </Card>

          <Card>
            <SegmentTimeline
              durationS={duration}
              currentTimeS={currentTime}
              segments={localSegments}
              selectedSegmentId={selectedSegmentId}
              onSeek={(s) => playerHandleRef.current?.seek(s)}
              onSelectSegment={setSelectedSegmentId}
              onSegmentDrag={onSegmentDrag}
              onCreate={onCreateRange}
            />
          </Card>
        </div>

        <div>
          <h3 className="text-xs uppercase tracking-wider text-ink-faint mb-2">
            Segments ({localSegments.length})
          </h3>
          {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}
          <SegmentSidebar
            segments={localSegments}
            selectedSegmentId={selectedSegmentId}
            onSelect={setSelectedSegmentId}
            onUpdate={(id, patch) => updateMut.mutate({ id, patch })}
            onDelete={(id) => deleteMut.mutate(id)}
            onPublish={onPublish}
            publishingId={publishingId}
            savingId={savingId}
          />
        </div>
      </div>
    </div>
  );
}
