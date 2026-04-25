import { useState, useEffect } from "react";
import { useSettings, useUpdateSettings } from "@/lib/query";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { SettingsPatch } from "@/lib/api";

export default function SettingsPage() {
  const { data, isLoading, error } = useSettings();
  const update = useUpdateSettings();

  const [form, setForm] = useState<SettingsPatch>({});
  useEffect(() => {
    if (data) setForm({});
  }, [data]);

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
      </Card>

      <div className="flex gap-2">
        <Button variant="primary" onClick={save} disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
        {update.isSuccess && <span className="text-sage text-xs self-center">Saved ✓</span>}
        {update.isError && (
          <span className="text-terracotta text-xs self-center">Error: {update.error.message}</span>
        )}
      </div>
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
