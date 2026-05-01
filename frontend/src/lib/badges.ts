import type { RecordingStatus } from "@/lib/api";
import type { BadgeColor } from "@/components/ui/badge";

export const STATUS_META: Record<RecordingStatus, { color: BadgeColor; label: string }> = {
  recording: { color: "live", label: "Recording" },
  complete: { color: "done", label: "Complete" },
  failed: { color: "failed", label: "Failed" }, // technically reserved for live but must exist for the type
  interrupted: { color: "neutral", label: "Interrupted" },
  vod_queued: { color: "scheduled", label: "Queued" },
  vod_downloading: { color: "buffering", label: "Downloading" },
  vod_failed: { color: "failed", label: "Failed" },
};