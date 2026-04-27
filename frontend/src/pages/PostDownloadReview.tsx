import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  useRecording,
  useStream,
  useSegments,
  useCreateSegment,
  useUpdateSegment,
  usePublishSegment,
} from "@/lib/query";
import { COMMON_GENRES } from "@/lib/genres";
import { cn } from "@/lib/utils";
import type { SegmentCreate } from "@/lib/api";

// ─── helpers ────────────────────────────────────────────────────────────────

function fmt(s: number): string {
  const sec = Math.max(0, Math.floor(s));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const r = sec % 60;
  return h > 0
    ? `${h}:${m.toString().padStart(2, "0")}:${r.toString().padStart(2, "0")}`
    : `${m}:${r.toString().padStart(2, "0")}`;
}

function parseSetlistLine(line: string): { timecode: string; title: string } | null {
  const m = line.match(/^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$/);
  if (!m) return null;
  return { timecode: m[1], title: m[2].trim() };
}

function timecodeToSeconds(tc: string): number {
  const parts = tc.split(":").map(Number);
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return 0;
}

function parseSetlistText(text: string, totalDuration: number): Array<{ timecode: string; title: string; start_s: number; end_s: number }> {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const parsed = lines.map(parseSetlistLine).filter(Boolean) as Array<{ timecode: string; title: string }>;
  return parsed.map((entry, i) => {
    const start_s = timecodeToSeconds(entry.timecode);
    const next = parsed[i + 1];
    const end_s = next ? timecodeToSeconds(next.timecode) : totalDuration;
    return { ...entry, start_s, end_s };
  });
}

// ─── GenresInput ─────────────────────────────────────────────────────────────

function GenresInput({
  value,
  onChange,
  youtubeTags,
}: {
  value: string;
  onChange: (v: string) => void;
  youtubeTags?: string[] | null;
}) {
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const currentGenres = value
    ? value.split(",").map((g) => g.trim()).filter(Boolean)
    : [];

  const lastToken = value.split(",").pop()?.trim() ?? "";

  const suggestions = lastToken.length > 0
    ? COMMON_GENRES.filter(
        (g) =>
          g.toLowerCase().startsWith(lastToken.toLowerCase()) &&
          !currentGenres.includes(g),
      )
    : [];

  const addGenre = (genre: string) => {
    const parts = value.split(",").map((g) => g.trim()).filter(Boolean);
    if (lastToken) {
      parts[parts.length - 1] = genre;
    } else {
      parts.push(genre);
    }
    onChange(parts.join(", "));
    setShowSuggestions(false);
    inputRef.current?.focus();
  };

  const addTag = (tag: string) => {
    const parts = value.split(",").map((g) => g.trim()).filter(Boolean);
    if (!parts.includes(tag)) {
      parts.push(tag);
      onChange(parts.join(", "));
    }
  };

  return (
    <div className="relative">
      <div className="relative">
        <Input
          ref={inputRef}
          value={value}
          placeholder="Genres (comma-separated)"
          onChange={(e) => { onChange(e.target.value); setShowSuggestions(true); }}
          onFocus={() => setShowSuggestions(true)}
          onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
          className="text-xs"
        />
        {showSuggestions && suggestions.length > 0 && (
          <div className="absolute z-20 mt-0.5 w-full rounded border border-border bg-surface-1 shadow-md max-h-32 overflow-auto">
            {suggestions.map((s) => (
              <button
                key={s}
                className="block w-full text-left px-2 py-1 text-xs hover:bg-surface-3 text-ink"
                onMouseDown={(e) => { e.preventDefault(); addGenre(s); }}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
      {youtubeTags && youtubeTags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          <span className="text-[10px] text-ink-faint self-center">YouTube tags:</span>
          {youtubeTags.slice(0, 12).map((tag) => {
            const already = currentGenres.includes(tag);
            return (
              <button
                key={tag}
                disabled={already}
                onClick={() => addTag(tag)}
                className={cn(
                  "px-1.5 py-0.5 rounded text-[10px] border transition-colors",
                  already
                    ? "border-border text-ink-faint cursor-default"
                    : "border-border hover:border-terracotta text-ink-dim hover:text-terracotta cursor-pointer",
                )}
              >
                {tag}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── SegmentRow ──────────────────────────────────────────────────────────────

interface SegmentDraft {
  id?: number;        // set if already in DB
  artist: string;
  title: string;
  start_s: number;
  end_s: number;
  genres: string;
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function PostDownloadReviewPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const recordingId = Number(id);

  const { data: recording, isLoading: recLoading } = useRecording(recordingId);
  const { data: stream, isLoading: streamLoading } = useStream(recording?.stream_id ?? 0);
  const { data: existingSegments = [] } = useSegments(recordingId);

  const createMut = useCreateSegment(recordingId);
  const updateMut = useUpdateSegment(recordingId);
  const publishMut = usePublishSegment(recordingId);

  const [descExpanded, setDescExpanded] = useState(false);
  const [setlistDismissed, setSetlistDismissed] = useState(false);
  const [drafts, setDrafts] = useState<SegmentDraft[]>([]);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  const duration = stream?.duration_s ?? recording?.duration_s ?? 0;

  // Initialize drafts from existing segments or build defaults
  useEffect(() => {
    if (existingSegments.length > 0) {
      setDrafts(
        existingSegments.map((s) => ({
          id: s.id,
          artist: s.artist,
          title: s.title ?? "",
          start_s: s.start_s,
          end_s: s.end_s,
          genres: s.genres ?? "",
        }))
      );
      return;
    }

    // No existing segments — build from detected setlist or whole-video default
    if (stream?.detected_setlist_text && !setlistDismissed) {
      return; // will be populated when user clicks "Apply as song list"
    }

    if (stream && !setlistDismissed) {
      // Whole-video default
      setDrafts([{
        artist: "",
        title: stream.title ?? "",
        start_s: 0,
        end_s: duration,
        genres: "",
      }]);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingSegments, stream]);

  const applySetlist = () => {
    if (!stream?.detected_setlist_text) return;
    const entries = parseSetlistText(stream.detected_setlist_text, duration);
    setDrafts(entries.map((e) => ({
      artist: "",
      title: e.title,
      start_s: e.start_s,
      end_s: e.end_s,
      genres: "",
    })));
    setSetlistDismissed(true);
  };

  const dismissSetlist = () => setSetlistDismissed(true);

  const updateDraft = (idx: number, patch: Partial<SegmentDraft>) => {
    setDrafts((ds) => ds.map((d, i) => i === idx ? { ...d, ...patch } : d));
  };

  const saveDrafts = async () => {
    setSaveStatus("saving");
    try {
      for (const d of drafts) {
        const payload: SegmentCreate = {
          recording_id: recordingId,
          artist: d.artist || "Untitled",
          title: d.title || null,
          start_s: d.start_s,
          end_s: d.end_s,
          source: "manual",
          genres: d.genres || null,
        };
        if (d.id) {
          await updateMut.mutateAsync({ id: d.id, patch: { artist: payload.artist, title: payload.title, genres: payload.genres } });
        } else {
          await createMut.mutateAsync(payload);
        }
      }
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch {
      setSaveStatus("error");
    }
  };

  const publishAll = async () => {
    await saveDrafts();
    for (const seg of existingSegments) {
      if (seg.status === "draft") {
        await publishMut.mutateAsync({ id: seg.id, options: {} });
      }
    }
  };

  if (recLoading || streamLoading) {
    return <div className="text-ink-dim text-xs p-8">Loading…</div>;
  }

  if (!recording || !stream) {
    return <div className="text-terracotta text-xs p-8">Recording or stream not found.</div>;
  }

  const description = stream.description ?? null;
  const shortDesc = description ? description.slice(0, 200) : null;
  const showReadMore = description && description.length > 200;

  const hasDetectedSetlist = !!stream.detected_setlist_text && !setlistDismissed;

  return (
    <div className="max-w-3xl">
      {/* Header */}
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Post-download review</h2>
        <Link to="/recordings" className="ml-3 text-xs text-ink-dim hover:text-ink">
          ← Recordings
        </Link>
      </div>

      {/* Stream metadata card */}
      <Card className="mb-4 flex gap-4">
        {stream.thumbnail_url && (
          <img
            src={stream.thumbnail_url}
            alt=""
            className="w-40 rounded flex-shrink-0 object-cover self-start"
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-base truncate">{stream.title}</div>
          <div className="text-xs text-ink-dim mt-0.5 flex items-center gap-2 flex-wrap">
            <span>{stream.channel_name}</span>
            {stream.upload_date && <span>· {stream.upload_date}</span>}
            {duration > 0 && <span>· {fmt(duration)}</span>}
          </div>
          {description && (
            <div className="mt-2 text-xs text-ink-dim">
              <p className={descExpanded ? undefined : "line-clamp-3"}>
                {descExpanded ? description : (shortDesc ?? description)}
              </p>
              {showReadMore && (
                <button
                  onClick={() => setDescExpanded((e) => !e)}
                  className="text-terracotta text-[11px] mt-1 hover:underline"
                >
                  {descExpanded ? "Show less" : "Show more"}
                </button>
              )}
            </div>
          )}
        </div>
      </Card>

      {/* Detected setlist card */}
      {hasDetectedSetlist && (
        <Card className="mb-4 border-l-4 border-l-sage">
          <CardLabel className="mb-2">Detected setlist</CardLabel>
          <p className="text-[11px] text-ink-faint mb-2">
            Source: <span className="text-ink-dim">{stream.detected_setlist_source ?? "auto"}</span>
          </p>
          <pre className="text-xs text-ink-dim font-mono whitespace-pre-wrap max-h-48 overflow-auto bg-surface-0 rounded p-2 mb-3">
            {stream.detected_setlist_text}
          </pre>
          <div className="flex gap-2 flex-wrap">
            <Button variant="primary" onClick={applySetlist}>
              Apply as song list
            </Button>
            <Button
              onClick={() => {
                applySetlist();
                navigate(`/timeline/${recordingId}`);
              }}
            >
              Open in Timeline editor
            </Button>
            <Button variant="ghost" onClick={dismissSetlist}>
              Dismiss
            </Button>
          </div>
        </Card>
      )}

      {/* Segments form */}
      <Card className="mb-4">
        <CardLabel className="mb-3">Segments ({drafts.length})</CardLabel>
        {drafts.length === 0 && (
          <p className="text-xs text-ink-dim">
            No segments yet. Apply the setlist above, or{" "}
            <button
              className="text-terracotta hover:underline"
              onClick={() =>
                setDrafts([{ artist: "", title: stream.title ?? "", start_s: 0, end_s: duration, genres: "" }])
              }
            >
              start with a whole-video segment
            </button>
            .
          </p>
        )}
        <div className="space-y-4">
          {drafts.map((d, i) => (
            <div key={i} className="border border-border rounded p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-amber whitespace-nowrap">
                  {fmt(d.start_s)} → {fmt(d.end_s)}
                </span>
                <span className="text-[10px] text-ink-faint">
                  ({fmt(d.end_s - d.start_s)})
                </span>
                {d.id && <Badge color="done">saved</Badge>}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[10px] text-ink-faint mb-0.5">Artist</label>
                  <Input
                    value={d.artist}
                    placeholder="Artist"
                    onChange={(e) => updateDraft(i, { artist: e.target.value })}
                    className="text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-ink-faint mb-0.5">Title</label>
                  <Input
                    value={d.title}
                    placeholder="Title (optional)"
                    onChange={(e) => updateDraft(i, { title: e.target.value })}
                    className="text-xs"
                  />
                </div>
              </div>
              <div>
                <label className="block text-[10px] text-ink-faint mb-0.5">Genres</label>
                <GenresInput
                  value={d.genres}
                  onChange={(v) => updateDraft(i, { genres: v })}
                  youtubeTags={stream.youtube_tags}
                />
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Footer actions */}
      <div className="flex gap-2 flex-wrap pb-8">
        <Button
          variant="primary"
          onClick={saveDrafts}
          disabled={saveStatus === "saving"}
        >
          {saveStatus === "saving" ? "Saving…" : "Save as draft"}
        </Button>
        <Button
          onClick={() => {
            saveDrafts();
            navigate(`/timeline/${recordingId}`);
          }}
        >
          Open in Timeline editor
        </Button>
        <Button
          onClick={publishAll}
          disabled={saveStatus === "saving"}
        >
          Publish to Emby
        </Button>
        {saveStatus === "saved" && (
          <span className="text-sage text-xs self-center">Saved</span>
        )}
        {saveStatus === "error" && (
          <span className="text-terracotta text-xs self-center">Save failed</span>
        )}
      </div>
    </div>
  );
}
