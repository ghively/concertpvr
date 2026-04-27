import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Dialog, DialogHeader, DialogBody, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { api, watchersApi, playlistApi } from "@/lib/api";
import { keys } from "@/lib/query";
import type {
  ProbeResult,
  ProbeStreamResult,
  ProbeChannelResult,
  ProbePlaylistResult,
  ProbePlaylistItem,
} from "@/lib/api";

// Type guards
function isStreamResult(r: ProbeResult): r is ProbeStreamResult {
  return !("type" in r);
}
function isChannelResult(r: ProbeResult): r is ProbeChannelResult {
  return "type" in r && r.type === "channel";
}
function isPlaylistResult(r: ProbeResult): r is ProbePlaylistResult {
  return "type" in r && r.type === "playlist";
}

type ModalState = "input" | "loading" | "result" | "error";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SmartPasteModal({ open, onOpenChange }: Props) {
  const [url, setUrl] = useState("");
  const [state, setState] = useState<ModalState>("input");
  const [result, setResult] = useState<ProbeResult | null>(null);
  const [error, setError] = useState<string>("");
  const navigate = useNavigate();
  const qc = useQueryClient();

  const handleClose = () => {
    onOpenChange(false);
    // Reset after close animation
    setTimeout(() => {
      setUrl("");
      setState("input");
      setResult(null);
      setError("");
    }, 150);
  };

  const probe = useMutation<ProbeResult, Error, string>({
    mutationFn: (u) => api.post<ProbeResult>("/api/streams", { url: u }),
    onMutate: () => setState("loading"),
    onSuccess: (data) => {
      setResult(data);
      setState("result");
    },
    onError: (err) => {
      setError(err.message ?? "Unknown error");
      setState("error");
    },
  });

  const handleProbe = () => {
    if (!url.trim()) return;
    probe.mutate(url.trim());
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      {state === "input" && (
        <InputView
          url={url}
          setUrl={setUrl}
          onProbe={handleProbe}
          onCancel={handleClose}
        />
      )}
      {state === "loading" && <LoadingView />}
      {state === "result" && result && (
        <>
          {isStreamResult(result) && (
            <StreamResultView
              result={result}
              onSuccess={() => {
                qc.invalidateQueries({ queryKey: keys.streams });
                qc.invalidateQueries({ queryKey: keys.recordings() });
                handleClose();
                if (result.kind === "video") {
                  navigate(`/recordings`);
                }
              }}
              onCancel={handleClose}
            />
          )}
          {isChannelResult(result) && (
            <ChannelResultView
              result={result}
              onSuccess={() => {
                qc.invalidateQueries({ queryKey: ["channel-watchers"] });
                handleClose();
                navigate(`/watchers`);
              }}
              onCancel={handleClose}
            />
          )}
          {isPlaylistResult(result) && (
            <PlaylistResultView
              result={result}
              onSuccess={() => {
                qc.invalidateQueries({ queryKey: keys.recordings() });
                handleClose();
              }}
              onCancel={handleClose}
            />
          )}
        </>
      )}
      {state === "error" && (
        <ErrorView message={error} onBack={() => setState("input")} onCancel={handleClose} />
      )}
    </Dialog>
  );
}

// ── Sub-views ─────────────────────────────────────────────────────────────────

function InputView({
  url,
  setUrl,
  onProbe,
  onCancel,
}: {
  url: string;
  setUrl: (v: string) => void;
  onProbe: () => void;
  onCancel: () => void;
}) {
  return (
    <>
      <DialogHeader>Add URL</DialogHeader>
      <DialogBody>
        <p className="text-xs text-ink-dim mb-3">
          Paste a YouTube video, channel, or playlist URL.
        </p>
        <Input
          autoFocus
          placeholder="https://www.youtube.com/watch?v=..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onProbe()}
        />
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" onClick={onProbe} disabled={!url.trim()}>
          Probe
        </Button>
      </DialogFooter>
    </>
  );
}

function LoadingView() {
  return (
    <>
      <DialogHeader>Probing…</DialogHeader>
      <DialogBody>
        <div className="flex items-center justify-center py-8 gap-3 text-ink-dim text-xs">
          <svg
            className="animate-spin h-5 w-5 text-terracotta"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8v8H4z"
            />
          </svg>
          <span>Probing URL…</span>
        </div>
      </DialogBody>
    </>
  );
}

function ErrorView({
  message,
  onBack,
  onCancel,
}: {
  message: string;
  onBack: () => void;
  onCancel: () => void;
}) {
  return (
    <>
      <DialogHeader>Error</DialogHeader>
      <DialogBody>
        <p className="text-xs text-red-400">{message}</p>
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button onClick={onBack}>Back</Button>
      </DialogFooter>
    </>
  );
}

// ── Stream result (single video or live) ─────────────────────────────────────

function StreamResultView({
  result,
  onSuccess,
  onCancel,
}: {
  result: ProbeStreamResult;
  onSuccess: () => void;
  onCancel: () => void;
}) {
  // Stream was already created by the POST /api/streams call
  return (
    <>
      <DialogHeader>
        {result.kind === "live" ? "Live Stream" : "Video"} found
      </DialogHeader>
      <DialogBody>
        <div className="flex gap-4">
          {result.thumbnail_url && (
            <div className="w-32 aspect-video rounded overflow-hidden flex-shrink-0 bg-surface-0">
              <img
                src={result.thumbnail_url}
                alt=""
                className="w-full h-full object-cover"
              />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="font-medium text-sm leading-snug">{result.title}</div>
            <div className="text-xs text-ink-dim mt-1">{result.channel_name}</div>
            <div className="flex items-center gap-2 mt-2">
              <Badge color={result.kind === "live" ? "live" : "neutral"}>
                {result.kind}
              </Badge>
              {result.detected_setlist_source && (
                <span className="text-[10px] bg-sage/15 text-sage rounded px-2 py-0.5 uppercase tracking-wider">
                  Setlist detected
                </span>
              )}
            </div>
          </div>
        </div>
        {result.kind === "video" && (
          <p className="text-xs text-ink-dim mt-3">
            This video will be queued for download. You can track progress on the Recordings page.
          </p>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" onClick={() => onSuccess()}>
          {result.kind === "video" ? "Queue download" : "Add source"}
        </Button>
      </DialogFooter>
    </>
  );
}

// ── Channel result ────────────────────────────────────────────────────────────

function ChannelResultView({
  result,
  onSuccess,
  onCancel,
}: {
  result: ProbeChannelResult;
  onSuccess: () => void;
  onCancel: () => void;
}) {
  const [watchLive, setWatchLive] = useState(true);
  const [watchVod, setWatchVod] = useState(false);  // explicit opt-in
  const [autoPublish, setAutoPublish] = useState(false);

  const createWatcher = useMutation<
    Awaited<ReturnType<typeof watchersApi.create>>,
    Error,
    Parameters<typeof watchersApi.create>[0]
  >({
    mutationFn: (p) => watchersApi.create(p),
    onSuccess: () => onSuccess(),
  });

  const handleSubscribe = () => {
    createWatcher.mutate({
      channel_url: result.url,
      watch_live: watchLive,
      watch_vod_uploads: watchVod,
      auto_publish: autoPublish,
    });
  };

  return (
    <>
      <DialogHeader>Subscribe to channel</DialogHeader>
      <DialogBody>
        <div className="mb-4">
          <div className="font-medium text-sm">{result.channel_name}</div>
          <div className="text-xs text-ink-dim mt-0.5 truncate">{result.url}</div>
        </div>
        <p className="text-xs text-ink-dim mb-2">
          Subscribing only sets up monitoring. Choose what to do automatically:
        </p>
        <div className="space-y-3">
          <div className="flex flex-col gap-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={watchLive}
                onChange={(e) => setWatchLive(e.target.checked)}
                className="accent-terracotta"
              />
              <span className="text-sm">Auto-record live broadcasts</span>
            </label>
            <p className="text-xs text-ink-faint pl-5">
              When this channel goes live, start a buffer recording.
            </p>
          </div>
          <div className="flex flex-col gap-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={watchVod}
                onChange={(e) => setWatchVod(e.target.checked)}
                className="accent-terracotta"
              />
              <span className="text-sm">Auto-download new VOD uploads (forward only)</span>
            </label>
            <p className="text-xs text-ink-faint pl-5">
              Only uploads <strong>after</strong> subscribing get queued — never the
              backlog. Browse the Backlog tab on the watcher page to manually pick
              older videos.
            </p>
          </div>
          <div className="flex flex-col gap-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoPublish}
                onChange={(e) => setAutoPublish(e.target.checked)}
                className="accent-terracotta"
              />
              <span className="text-sm">Auto-publish to Emby</span>
            </label>
            <p className="text-xs text-ink-faint pl-5">
              Only enable for channels you trust completely (e.g. Tiny Desk, KEXP).
              Wrong artist regex = silently wrong metadata in your library.
            </p>
          </div>
        </div>
        {createWatcher.isError && (
          <p className="text-xs text-red-400 mt-2">{createWatcher.error?.message}</p>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button
          variant="primary"
          onClick={handleSubscribe}
          disabled={createWatcher.isPending}
        >
          Subscribe
        </Button>
      </DialogFooter>
    </>
  );
}

// ── Playlist result ───────────────────────────────────────────────────────────

function PlaylistResultView({
  result,
  onSuccess,
  onCancel,
}: {
  result: ProbePlaylistResult;
  onSuccess: () => void;
  onCancel: () => void;
}) {
  const [titleFilter, setTitleFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(
    new Set(result.items.map((i) => i.video_id)),
  );

  const ingest = useMutation<
    Awaited<ReturnType<typeof playlistApi.confirm>>,
    Error,
    Parameters<typeof playlistApi.confirm>[0]
  >({
    mutationFn: (p) => playlistApi.confirm(p),
    onSuccess: () => onSuccess(),
  });

  const filteredItems = result.items.filter((item) =>
    !titleFilter.trim() ||
    item.title.toLowerCase().includes(titleFilter.toLowerCase()),
  );

  const toggleItem = (id: string, disabled: boolean) => {
    if (disabled) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectCount = selected.size;

  return (
    <>
      <DialogHeader>
        Playlist: {result.playlist_title}
        <span className="text-xs text-ink-dim font-normal ml-2">({result.count} videos)</span>
      </DialogHeader>
      <DialogBody className="max-h-[60vh] overflow-y-auto">
        <Input
          placeholder="Filter by title…"
          value={titleFilter}
          onChange={(e) => setTitleFilter(e.target.value)}
          className="mb-3"
        />
        <div className="space-y-1">
          {filteredItems.map((item) => (
            <PlaylistItemRow
              key={item.video_id}
              item={item}
              checked={selected.has(item.video_id)}
              onToggle={(disabled) => toggleItem(item.video_id, disabled)}
            />
          ))}
        </div>
        {ingest.isError && (
          <p className="text-xs text-red-400 mt-2">{ingest.error?.message}</p>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button
          variant="primary"
          onClick={() => ingest.mutate({ video_ids: Array.from(selected) })}
          disabled={selectCount === 0 || ingest.isPending}
        >
          Queue {selectCount} download{selectCount !== 1 ? "s" : ""}
        </Button>
      </DialogFooter>
    </>
  );
}

function PlaylistItemRow({
  item,
  checked,
  onToggle,
}: {
  item: ProbePlaylistItem;
  checked: boolean;
  onToggle: (disabled: boolean) => void;
}) {
  // "already known" means it's already in our system — we'd need to check that
  // For now we treat all items as selectable
  const disabled = false;

  return (
    <label
      className={`flex items-center gap-2 rounded px-2 py-1.5 cursor-pointer text-xs ${
        disabled ? "opacity-40 cursor-not-allowed" : "hover:bg-surface-2"
      }`}
      onClick={(e) => {
        e.preventDefault();
        onToggle(disabled);
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={() => {}}
        className="accent-terracotta flex-shrink-0"
      />
      {item.thumbnail_url && (
        <div className="w-14 aspect-video rounded overflow-hidden flex-shrink-0 bg-surface-0">
          <img src={item.thumbnail_url} alt="" className="w-full h-full object-cover" />
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="truncate font-medium">{item.title}</div>
        <div className="text-ink-faint truncate">{item.channel}</div>
      </div>
    </label>
  );
}
