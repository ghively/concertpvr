import { useEffect, useState } from "react";
import { useSettings, useUpdateSettings, useSession } from "@/lib/query";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { authApi, type ApiError, type SettingsPatch } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function SettingsPage() {
  const { data, isLoading, error } = useSettings();
  const update = useUpdateSettings();
  const { data: session, refetch: refetchSession } = useSession();

  const [form, setForm] = useState<SettingsPatch>({});
  useEffect(() => {
    if (data) setForm({});
  }, [data]);

  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwSubmitting, setPwSubmitting] = useState(false);
  const [pwMessage, setPwMessage] = useState<
    { kind: "ok"; text: string } | { kind: "err"; text: string } | null
  >(null);

  if (isLoading) return <div className="text-ink-dim text-xs">Loading…</div>;
  if (error || !data) return <div className="text-terracotta text-xs">Failed to load settings.</div>;

  const field = <K extends keyof SettingsPatch>(k: K) => (v: SettingsPatch[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const merged = { ...data, ...form };

  const save = () => {
    const dirty: SettingsPatch = {};
    for (const k of Object.keys(form) as (keyof SettingsPatch)[]) {
      if (form[k] !== data[k]) (dirty as Record<string, unknown>)[k as string] = form[k];
    }
    if (Object.keys(dirty).length > 0) update.mutate(dirty);
  };

  const submitPassword = async () => {
    setPwMessage(null);
    if (!newPw) return;
    setPwSubmitting(true);
    try {
      await authApi.setPassword(newPw, session?.password_set ? currentPw : undefined);
      setCurrentPw(""); setNewPw("");
      setPwMessage({ kind: "ok", text: "Password updated." });
      refetchSession();
    } catch (e) {
      const err = e as ApiError;
      setPwMessage({
        kind: "err",
        text: err.status === 401 ? "Current password is incorrect." : err.message,
      });
    } finally {
      setPwSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <h2 className="text-lg font-semibold mb-4">Settings</h2>

      <Card className="mb-4 space-y-3">
        <CardLabel>Emby Integration</CardLabel>
        <Labeled label="Emby server URL" help="Used to trigger library refresh after publish">
          <Input
            className="font-mono"
            value={merged.emby_url ?? ""}
            onChange={(e) => field("emby_url")(e.target.value || null)}
            placeholder="http://192.168.1.10:8096"
          />
        </Labeled>
        <Labeled label="API key">
          <Input
            type="password"
            className="font-mono"
            value={merged.emby_api_key ?? ""}
            onChange={(e) => field("emby_api_key")(e.target.value || null)}
          />
        </Labeled>
        <Labeled label="Movies library path (Emby's view)">
          <Input
            className="font-mono"
            value={merged.emby_library_path ?? ""}
            onChange={(e) => field("emby_library_path")(e.target.value || null)}
            placeholder="/media/concerts"
          />
        </Labeled>
      </Card>

      <Card className="mb-4 space-y-3">
        <CardLabel>Naming</CardLabel>
        <Labeled
          label="Folder pattern"
          help="Tokens: {artist} {festival} {venue} {year} {date} {title}"
        >
          <Input
            className="font-mono"
            value={merged.folder_pattern}
            onChange={(e) => field("folder_pattern")(e.target.value)}
          />
        </Labeled>
      </Card>

      <Card className="mb-4 space-y-3">
        <CardLabel>Recording defaults</CardLabel>
        <Labeled label="Default quality (yt-dlp format selector)">
          <Input
            className="font-mono"
            value={merged.default_quality}
            onChange={(e) => field("default_quality")(e.target.value)}
          />
        </Labeled>
        <Labeled label="Default retention (days)">
          <Input
            type="number"
            className="font-mono"
            value={merged.default_retention_days}
            onChange={(e) => field("default_retention_days")(Number(e.target.value))}
          />
        </Labeled>
        <Labeled label="Max concurrent recordings">
          <Input
            type="number"
            className="font-mono"
            value={merged.max_concurrent_recordings}
            onChange={(e) => field("max_concurrent_recordings")(Number(e.target.value))}
          />
        </Labeled>
        <Labeled
          label="Max concurrent VOD downloads"
          help="VOD queue capacity (separate from live)."
        >
          <Input
            type="number"
            className="font-mono"
            min={1}
            max={8}
            value={merged.max_concurrent_vod_downloads ?? 2}
            onChange={(e) => field("max_concurrent_vod_downloads")(Number(e.target.value))}
          />
        </Labeled>
        <Labeled
          label="Auto-prune buffer when disk full"
          help="When the buffer drive drops below 5% free, prune oldest fragments across all streams (ignores per-stream retention)."
        >
          <button
            onClick={() => field("auto_prune_when_full")(!merged.auto_prune_when_full)}
            className={cn(
              "w-9 h-5 rounded-full relative transition-colors",
              merged.auto_prune_when_full ? "bg-sage/30" : "bg-surface-3",
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 w-4 h-4 rounded-full transition-all",
                merged.auto_prune_when_full ? "left-[18px] bg-sage" : "left-0.5 bg-ink-dim",
              )}
            />
          </button>
        </Labeled>
        <Labeled
          label="Auto-delete source after publish"
          help="When all segments on a recording are published, source file is removed. You won't be able to re-cut."
        >
          <button
            onClick={() => field("auto_delete_source_after_publish")(!merged.auto_delete_source_after_publish)}
            className={cn(
              "w-9 h-5 rounded-full relative transition-colors",
              merged.auto_delete_source_after_publish ? "bg-sage/30" : "bg-surface-3",
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 w-4 h-4 rounded-full transition-all",
                merged.auto_delete_source_after_publish ? "left-[18px] bg-sage" : "left-0.5 bg-ink-dim",
              )}
            />
          </button>
        </Labeled>
      </Card>

      <Card className="mb-4 space-y-3">
        <CardLabel>yt-dlp</CardLabel>
        <Labeled
          label="Cookies file path"
          help="Optional. Export your YouTube cookies and place the file in /data/. Required for member-only or age-gated streams."
        >
          <Input
            className="font-mono"
            value={merged.yt_dlp_cookies_path ?? ""}
            onChange={(e) => field("yt_dlp_cookies_path")(e.target.value || null)}
            placeholder="/data/cookies.txt"
          />
        </Labeled>
      </Card>

      <div className="flex gap-2 mb-8">
        <Button variant="primary" onClick={save} disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
        {update.isSuccess && <span className="text-sage text-xs self-center">Saved ✓</span>}
        {update.isError && (
          <span className="text-terracotta text-xs self-center">Error: {update.error.message}</span>
        )}
      </div>

      <Card className="space-y-3">
        <CardLabel>Password</CardLabel>
        <p className="text-xs text-ink-dim">
          {session?.password_set
            ? "Change your password. You'll stay signed in on this device."
            : "Set a password to require sign-in for the web UI. Until you do, anyone on the LAN can access the app."}
        </p>
        {session?.password_set && (
          <Labeled label="Current password">
            <Input
              type="password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
            />
          </Labeled>
        )}
        <Labeled label="New password">
          <Input
            type="password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
          />
        </Labeled>
        {pwMessage && (
          <p className={cn(
            "text-xs",
            pwMessage.kind === "ok" ? "text-sage" : "text-red-400",
          )}>
            {pwMessage.text}
          </p>
        )}
        <Button variant="primary" onClick={submitPassword} disabled={pwSubmitting || !newPw}>
          {pwSubmitting ? "Updating…" : session?.password_set ? "Change password" : "Set password"}
        </Button>
      </Card>
    </div>
  );
}

function Labeled({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-[11px] text-ink-dim mb-1">{label}</label>
      {children}
      {help && <div className="text-[10px] text-ink-faint mt-1">{help}</div>}
    </div>
  );
}
