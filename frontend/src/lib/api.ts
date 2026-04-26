export class ApiError extends Error {
  constructor(public status: number, public body: unknown, message?: string) {
    super(message ?? `API error: ${status}`);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  const text = await res.text();
  const json = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) throw new ApiError(res.status, json);
  return json as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b),
  patch: <T>(p: string, b?: unknown) => request<T>("PATCH", p, b),
  delete: <T>(p: string) => request<T>("DELETE", p),
};

export type Settings = {
  emby_url: string | null;
  emby_api_key: string | null;
  emby_library_path: string | null;
  folder_pattern: string;
  default_quality: string;
  default_retention_days: number;
  max_concurrent_recordings: number;
  auto_prune_when_full: boolean;
  yt_dlp_cookies_path: string | null;
};

export type SettingsPatch = Partial<Settings>;

export const settingsApi = {
  get: () => api.get<Settings>("/api/settings"),
  patch: (p: SettingsPatch) => api.patch<Settings>("/api/settings", p),
};

// ── Streams ─────────────────────────────────────────────────────────────────

export type StreamKind = "channel" | "video" | "live";

export type Stream = {
  id: number;
  kind: StreamKind;
  youtube_id: string;
  url: string;
  title: string;
  channel_name: string;
  thumbnail_url: string | null;
  added_at: string;
};

export const streamsApi = {
  list: () => api.get<Stream[]>("/api/streams"),
  get: (id: number) => api.get<Stream>(`/api/streams/${id}`),
  create: (url: string) => api.post<Stream>("/api/streams", { url }),
  delete: (id: number) => api.delete<void>(`/api/streams/${id}`),
};

// ── Watch subscriptions ─────────────────────────────────────────────────────

export type WatchSubscription = {
  id: number;
  stream_id: number;
  enabled: boolean;
  title_filter: string | null;
  quality_cap: string | null;
  retention_days: number;
};

export type WatchSubscriptionPatch = Partial<Omit<WatchSubscription, "id" | "stream_id">>;

export const watchApi = {
  get: (streamId: number) => api.get<WatchSubscription>(`/api/streams/${streamId}/watch`),
  patch: (streamId: number, p: WatchSubscriptionPatch) =>
    api.patch<WatchSubscription>(`/api/streams/${streamId}/watch`, p),
};

// ── Recordings ──────────────────────────────────────────────────────────────

export type RecordingStatus = "recording" | "complete" | "failed" | "interrupted";

export type Recording = {
  id: number;
  stream_id: number;
  started_at: string;
  ended_at: string | null;
  path: string;
  duration_s: number;
  size_bytes: number;
  width: number | null;
  height: number | null;
  fps: number | null;
  status: RecordingStatus;
  is_buffer: boolean;
  error: string | null;
};

export const recordingsApi = {
  list: (streamId?: number) => {
    const qs = streamId !== undefined ? `?stream_id=${streamId}` : "";
    return api.get<Recording[]>(`/api/recordings${qs}`);
  },
  get: (id: number) => api.get<Recording>(`/api/recordings/${id}`),
};
