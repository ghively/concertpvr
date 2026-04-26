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

// ── Segments ────────────────────────────────────────────────────────────────

export type SegmentSource = "chapter" | "setlist" | "manual";
export type SegmentStatus = "draft" | "publishing" | "published" | "publish_failed";

export type Segment = {
  id: number;
  recording_id: number;
  artist: string;
  title: string | null;
  start_s: number;
  end_s: number;
  source: SegmentSource;
  status: SegmentStatus;
  error: string | null;
  emby_path: string | null;
  poster_path: string | null;
  nfo_path: string | null;
};

export type SegmentCreate = {
  recording_id: number;
  artist: string;
  title?: string | null;
  start_s: number;
  end_s: number;
  source?: SegmentSource;
};

export type SegmentPatch = {
  artist?: string;
  title?: string | null;
  start_s?: number;
  end_s?: number;
};

export type PublishOptions = {
  festival?: string | null;
  venue?: string | null;
  year?: number | null;
};

export const segmentsApi = {
  list: (recordingId: number) =>
    api.get<Segment[]>(`/api/segments?recording_id=${recordingId}`),
  create: (p: SegmentCreate) => api.post<Segment>("/api/segments", p),
  patch: (id: number, p: SegmentPatch) => api.patch<Segment>(`/api/segments/${id}`, p),
  delete: (id: number) => api.delete<void>(`/api/segments/${id}`),
  publish: (id: number, opts: PublishOptions) =>
    api.post<Segment>(`/api/segments/${id}/publish`, opts),
};

// ── Setlists ────────────────────────────────────────────────────────────────

export type SetlistEntry = { artist: string; start_s: number; end_s: number };

export const setlistsApi = {
  get: (recordingId: number) =>
    api.get<(SetlistEntry & { id: number; recording_id: number })[]>(
      `/api/recordings/${recordingId}/setlist`,
    ),
  replace: (recordingId: number, entries: SetlistEntry[]) =>
    api.post<unknown>(`/api/recordings/${recordingId}/setlist`, { entries }),
  paste: async (recordingId: number, text: string) => {
    const res = await fetch(`/api/recordings/${recordingId}/setlist/paste`, {
      method: "POST",
      headers: { "content-type": "text/plain" },
      body: text,
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, body);
    }
    return res.json();
  },
};

export const recordingMediaUrl = (id: number) => `/api/recordings/${id}/media`;

// ── Schedules ───────────────────────────────────────────────────────────────

export type ScheduleStatus = "pending" | "running" | "complete" | "failed" | "cancelled";

export type Schedule = {
  id: number;
  stream_id: number;
  starts_at: string;
  ends_at: string;
  artist: string | null;
  status: ScheduleStatus;
  error: string | null;
  recording_id: number | null;
};

export type ScheduleCreate = {
  url?: string;
  stream_id?: number;
  starts_at: string;
  ends_at: string;
  artist?: string | null;
};

export type SchedulePatch = {
  starts_at?: string;
  ends_at?: string;
  artist?: string | null;
  status?: "pending" | "cancelled";
};

export const schedulesApi = {
  list: () => api.get<Schedule[]>("/api/schedules"),
  get: (id: number) => api.get<Schedule>(`/api/schedules/${id}`),
  create: (p: ScheduleCreate) => api.post<Schedule>("/api/schedules", p),
  patch: (id: number, p: SchedulePatch) => api.patch<Schedule>(`/api/schedules/${id}`, p),
  delete: (id: number) => api.delete<void>(`/api/schedules/${id}`),
};
