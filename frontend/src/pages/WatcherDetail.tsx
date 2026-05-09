import { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useChannelWatcher, useUpdateChannelWatcher } from "@/lib/query";
import { BacklogBrowser } from "@/components/BacklogBrowser";
import type { ChannelWatcher, ChannelWatcherPatch, VodSegmentationMode } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tab = "settings" | "backlog";

function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return "just now";
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h ago`;
  return `${Math.round(ms / 86_400_000)}d ago`;
}

// Tri-state select value for auto_delete_source_after_publish (null/true/false)
type AutoDeleteValue = "inherit" | "on" | "off";

function toAutoDeleteValue(v: boolean | null | undefined): AutoDeleteValue {
  if (v === true) return "on";
  if (v === false) return "off";
  return "inherit";
}

function fromAutoDeleteValue(v: AutoDeleteValue): boolean | null {
  if (v === "on") return true;
  if (v === "off") return false;
  return null;
}

// ── Settings form ────────────────────────────────────────────────────────────

function SettingsTab({ watcher }: { watcher: ChannelWatcher }) {
  const update = useUpdateChannelWatcher();

  // Form state mirrors the watcher fields
  const [watchLive, setWatchLive] = useState(watcher.watch_live ?? true);
  const [watchVod, setWatchVod] = useState(watcher.watch_vod_uploads ?? false);
  const [vodTitleFilter, setVodTitleFilter] = useState(watcher.vod_title_filter ?? "");
  const [vodArtistRegex, setVodArtistRegex] = useState(watcher.vod_artist_regex ?? "");
  const [segMode, setSegMode] = useState<VodSegmentationMode>(
    watcher.vod_segmentation_mode ?? "chapters",
  );
  const [defaultGenres, setDefaultGenres] = useState(watcher.default_genres ?? "");
  const [autoPublish, setAutoPublish] = useState(watcher.auto_publish ?? false);
  const [extractSetlist, setExtractSetlist] = useState(
    watcher.extract_setlist_from_comments ?? false,
  );
  const [extractSetlistFm, setExtractSetlistFm] = useState(
    watcher.extract_setlist_from_setlistfm ?? false,
  );
  const [autoDelete, setAutoDelete] = useState<AutoDeleteValue>(
    toAutoDeleteValue(watcher.auto_delete_source_after_publish),
  );
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  // Sync if watcher prop changes (e.g. after refetch)
  useEffect(() => {
    setWatchLive(watcher.watch_live ?? true);
    setWatchVod(watcher.watch_vod_uploads ?? false);
    setVodTitleFilter(watcher.vod_title_filter ?? "");
    setVodArtistRegex(watcher.vod_artist_regex ?? "");
    setSegMode(watcher.vod_segmentation_mode ?? "chapters");
    setDefaultGenres(watcher.default_genres ?? "");
    setAutoPublish(watcher.auto_publish ?? false);
    setExtractSetlist(watcher.extract_setlist_from_comments ?? false);
    setExtractSetlistFm(watcher.extract_setlist_from_setlistfm ?? false);
    setAutoDelete(toAutoDeleteValue(watcher.auto_delete_source_after_publish));
    setDirty(false);
  }, [watcher]);

  const markDirty = () => {
    setDirty(true);
    setSaved(false);
  };

  const handleSave = () => {
    const patch: ChannelWatcherPatch = {
      watch_live: watchLive,
      watch_vod_uploads: watchVod,
      vod_title_filter: vodTitleFilter.trim() || null,
      vod_artist_regex: vodArtistRegex.trim() || null,
      vod_segmentation_mode: segMode,
      default_genres: defaultGenres.trim() || null,
      auto_publish: autoPublish,
      extract_setlist_from_comments: extractSetlist,
      extract_setlist_from_setlistfm: extractSetlistFm,
      auto_delete_source_after_publish: fromAutoDeleteValue(autoDelete),
    };
    update.mutate(
      { id: watcher.id, patch },
      {
        onSuccess: () => {
          setDirty(false);
          setSaved(true);
          setTimeout(() => setSaved(false), 2000);
        },
      },
    );
  };

  const handleCancel = () => {
    setWatchLive(watcher.watch_live ?? true);
    setWatchVod(watcher.watch_vod_uploads ?? false);
    setVodTitleFilter(watcher.vod_title_filter ?? "");
    setVodArtistRegex(watcher.vod_artist_regex ?? "");
    setSegMode(watcher.vod_segmentation_mode ?? "chapters");
    setDefaultGenres(watcher.default_genres ?? "");
    setAutoPublish(watcher.auto_publish ?? false);
    setExtractSetlist(watcher.extract_setlist_from_comments ?? false);
    setExtractSetlistFm(watcher.extract_setlist_from_setlistfm ?? false);
    setAutoDelete(toAutoDeleteValue(watcher.auto_delete_source_after_publish));
    setDirty(false);
    setSaved(false);
  };

  // Helper sub-components
  const Toggle = ({
    checked,
    onChange,
    label,
    helper,
  }: {
    checked: boolean;
    onChange: (v: boolean) => void;
    label: string;
    helper?: string;
  }) => (
    <div className="flex items-start gap-2.5 py-2">
      <button
        type="button"
        onClick={() => {
          onChange(!checked);
          markDirty();
        }}
        className={cn(
          "mt-0.5 w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center text-[11px] transition-colors",
          checked
            ? "bg-sage border-sage text-surface-0"
            : "bg-surface-2 border-border-strong text-transparent",
        )}
        aria-checked={checked}
        role="checkbox"
      >
        ✓
      </button>
      <div>
        <div className="text-[12px] text-ink">{label}</div>
        {helper && <div className="text-[10px] text-ink-faint mt-0.5 leading-relaxed">{helper}</div>}
      </div>
    </div>
  );

  const Field = ({
    label,
    helper,
    children,
  }: {
    label: string;
    helper?: React.ReactNode;
    children: React.ReactNode;
  }) => (
    <div className="mb-3.5">
      <label className="block text-[12px] text-ink mb-1">{label}</label>
      {children}
      {helper && (
        <p className="text-[10px] text-ink-faint mt-1 leading-relaxed">{helper}</p>
      )}
    </div>
  );

  const SectionTitle = ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div
      className={cn(
        "text-[11px] text-ink-faint uppercase tracking-wider font-semibold mb-2.5",
        className,
      )}
    >
      {children}
    </div>
  );

  return (
    <div>
      {/* Two-column grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* LEFT column */}
        <div>
          <SectionTitle>Watching for</SectionTitle>

          <Toggle
            checked={watchLive}
            onChange={setWatchLive}
            label="Live broadcasts"
            helper="Auto-record any new live broadcast on this channel."
          />
          <Toggle
            checked={watchVod}
            onChange={setWatchVod}
            label="New VOD uploads"
            helper="Forward-only — new videos posted from now on. Use the Backlog tab to pull older content."
          />

          <SectionTitle className="mt-6">VOD filters</SectionTitle>

          <Field
            label="Title filter (regex)"
            helper="Only download VODs whose title matches this. Empty = all uploads."
          >
            <Input
              className="font-mono"
              placeholder="Tiny Desk Concert"
              value={vodTitleFilter}
              onChange={(e) => { setVodTitleFilter(e.target.value); markDirty(); }}
            />
          </Field>

          <Field
            label="Artist extraction (regex with named group)"
            helper={
              <>
                Must include <code className="bg-surface-3 text-amber px-1 rounded text-[10px] font-mono">{"(?P<artist>…)"}</code> named group. No match → segment goes to manual review even if auto-publish is on.
              </>
            }
          >
            <Input
              className="font-mono text-[11px]"
              placeholder={`^(?P<artist>.+?)\\s*[:|]\\s*Tiny Desk Concert`}
              value={vodArtistRegex}
              onChange={(e) => { setVodArtistRegex(e.target.value); markDirty(); }}
            />
          </Field>

          <Field
            label="Segmentation mode"
            helper={
              <>
                <span className="font-mono text-ink-dim">chapters</span> — use YouTube chapters when present.{" "}
                <span className="font-mono text-ink-dim">whole-video</span> — treat the whole VOD as one segment.{" "}
                <span className="font-mono text-ink-dim">manual</span> — no auto-segmentation.
              </>
            }
          >
            <select
              className="w-full bg-surface-0 border border-border-strong rounded px-2.5 py-1.5 text-xs text-ink focus:outline-none focus:border-terracotta"
              value={segMode}
              onChange={(e) => { setSegMode(e.target.value as VodSegmentationMode); markDirty(); }}
            >
              <option value="chapters">chapters (use YouTube chapters when present)</option>
              <option value="whole-video">whole-video (treat the whole VOD as one segment)</option>
              <option value="manual">manual (no auto-segmentation)</option>
            </select>
          </Field>
        </div>

        {/* RIGHT column */}
        <div>
          <SectionTitle>Library defaults</SectionTitle>

          <Field
            label="Default genres"
            helper="Comma-separated. Applied to all segments from this watcher unless edited per-segment."
          >
            <Input
              placeholder="Indie, Alternative, Folk"
              value={defaultGenres}
              onChange={(e) => { setDefaultGenres(e.target.value); markDirty(); }}
            />
          </Field>

          <SectionTitle className="mt-6">Automation</SectionTitle>

          <Toggle
            checked={autoPublish}
            onChange={setAutoPublish}
            label="Auto-publish to Emby"
            helper="Only fires when the artist regex matches cleanly. Anything fuzzy falls back to manual review."
          />

          <Toggle
            checked={extractSetlist}
            onChange={setExtractSetlist}
            label="Extract setlists from comments"
            helper="Slower polling (~3–5s extra per upload). Ideal for channels where fans post setlists in comments."
          />

          <Toggle
            checked={extractSetlistFm}
            onChange={setExtractSetlistFm}
            label="Look up setlists on Setlist.fm"
            helper="Requires a Setlist.fm API key in Settings. Matched by channel name + upload date."
          />

          <div className="mb-3.5 mt-1">
            <label className="block text-[12px] text-ink mb-1">
              Auto-delete source after publish
            </label>
            <select
              className="w-full bg-surface-0 border border-border-strong rounded px-2.5 py-1.5 text-xs text-ink focus:outline-none focus:border-terracotta"
              value={autoDelete}
              onChange={(e) => { setAutoDelete(e.target.value as AutoDeleteValue); markDirty(); }}
            >
              <option value="inherit">Inherit from global settings</option>
              <option value="on">On — always delete source after publish</option>
              <option value="off">Off — keep source file</option>
            </select>
            <p className="text-[10px] text-ink-faint mt-1 leading-relaxed">
              Null (inherit) defers to the global auto-delete setting.
            </p>
          </div>
        </div>
      </div>

      {/* Save bar */}
      <div className="flex items-center justify-end gap-2 mt-6 pt-4 border-t border-border">
        {saved && (
          <span className="text-[11px] text-sage mr-2">Changes saved.</span>
        )}
        {update.isError && (
          <span className="text-[11px] text-red-400 mr-2">Save failed.</span>
        )}
        <Button variant="ghost" onClick={handleCancel} disabled={!dirty}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={handleSave}
          disabled={!dirty || update.isPending}
        >
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WatcherDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const watcherId = Number(id);
  const [tab, setTab] = useState<Tab>("settings");
  const update = useUpdateChannelWatcher();

  const { data: watcher, isLoading, isError } = useChannelWatcher(watcherId);

  if (isLoading) {
    return <p className="text-ink-dim text-xs p-8">Loading…</p>;
  }

  if (isError || !watcher) {
    return (
      <div className="p-8 text-center">
        <p className="text-red-400 text-sm mb-4">Watcher not found.</p>
        <Button variant="ghost" onClick={() => navigate("/watchers")}>
          ← Back to watchers
        </Button>
      </div>
    );
  }

  const toggleEnabled = () => {
    update.mutate({ id: watcher.id, patch: { enabled: !watcher.enabled } });
  };

  return (
    <div>
      {/* Breadcrumb */}
      <div className="text-[11px] text-ink-faint mb-2">
        <Link to="/watchers" className="hover:text-ink transition-colors">
          Watchers
        </Link>
        {" › "}
        <span className="text-ink">{watcher.channel_name}</span>
      </div>

      {/* Header */}
      <div className="flex items-center gap-4 mb-5 pb-4 border-b border-border">
        <div className="w-14 h-14 rounded-full bg-surface-3 flex-shrink-0 overflow-hidden">
          {watcher.avatar_url ? (
            <img src={watcher.avatar_url} alt="" className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-xl font-semibold text-ink-dim">
              {watcher.channel_name.charAt(0).toUpperCase()}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-[22px] font-semibold leading-tight">{watcher.channel_name}</h2>
          <div className="text-[12px] text-ink-dim mt-0.5">
            <a
              href={watcher.channel_url}
              target="_blank"
              rel="noreferrer"
              className="font-mono hover:text-ink transition-colors"
            >
              {watcher.channel_url}
            </a>
            {" · last polled "}
            {fmtRelative(watcher.last_polled)}
          </div>
        </div>
        {/* Enable toggle */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={toggleEnabled}
            className={cn(
              "w-4 h-4 rounded border flex items-center justify-center text-[11px] transition-colors",
              watcher.enabled
                ? "bg-sage border-sage text-surface-0"
                : "bg-surface-2 border-border-strong text-transparent",
            )}
            aria-label={watcher.enabled ? "Disable watcher" : "Enable watcher"}
            aria-checked={watcher.enabled}
            role="checkbox"
          >
            ✓
          </button>
          <span className="text-[12px] text-ink">Enabled</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border mb-5">
        {(["settings", "backlog"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-2.5 text-[13px] border-b-2 -mb-px transition-colors capitalize",
              tab === t
                ? "border-terracotta text-ink"
                : "border-transparent text-ink-dim hover:text-ink",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "settings" && <SettingsTab watcher={watcher} />}
      {tab === "backlog" && <BacklogBrowser watcherId={watcher.id} />}
    </div>
  );
}
