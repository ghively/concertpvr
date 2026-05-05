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
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    throw new ApiError(res.status, json);
  }
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
  // Path translation (v0.4.1)
  emby_path_local_prefix: string | null;
  emby_path_emby_prefix: string | null;
  folder_pattern: string;
  default_quality: string;
  default_retention_days: number;
  max_concurrent_recordings: number;
  auto_prune_when_full: boolean;
  yt_dlp_cookies_path: string | null;
  // VOD fields (v0.3)
  max_concurrent_vod_downloads: number;
  auto_delete_source_after_publish: boolean;
  // Setlist.fm (v0.4.1)
  setlistfm_api_key: string | null;
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
  // VOD metadata (v0.3)
  description?: string | null;
  original_upload_date?: string | null;
  youtube_tags?: string[] | null;
  detected_setlist_text?: string | null;
  detected_setlist_source?: string | null;
};

export const streamsApi = {
  list: () => api.get<Stream[]>("/api/streams"),
  get: (id: number) => api.get<Stream>(`/api/streams/${id}`),
  create: (url: string) => api.post<Stream>("/api/streams", { url }),
  delete: (id: number) => api.delete<void>(`/api/streams/${id}`),
  dvrPull: (id: number) =>
    api.post<{ recording_id: number }>(`/api/streams/${id}/dvr-pull`, {}),
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

export type RecordingStatus =
  | "recording"
  | "complete"
  | "failed"
  | "interrupted"
  | "vod_queued"
  | "vod_downloading"
  | "vod_failed"
  | "vod_cancelled";

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
  /** 0–100 download progress for vod_downloading */
  vod_pct?: number | null;
  /** seconds remaining for vod_downloading */
  vod_eta_s?: number | null;
  /** VOD fields (v0.3) */
  auto_publish_after_download?: boolean;
  source_deleted?: boolean;
};

export const recordingsApi = {
  list: (streamId?: number) => {
    const qs = streamId !== undefined ? `?stream_id=${streamId}` : "";
    return api.get<Recording[]>(`/api/recordings${qs}`);
  },
  get: (id: number) => api.get<Recording>(`/api/recordings/${id}`),
  getSchedule: (id: number) =>
    api.get<Schedule | null>(`/api/recordings/${id}/schedule`),
  cancel: (id: number) =>
    api.post<{ status: string; previous: string }>(`/api/recordings/${id}/cancel`, {}),
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
  genres?: string | null;
  original_upload_date?: string | null;
};

export type SegmentCreate = {
  recording_id: number;
  artist: string;
  title?: string | null;
  start_s: number;
  end_s: number;
  source?: SegmentSource;
  genres?: string | null;
};

export type SegmentPatch = {
  artist?: string;
  title?: string | null;
  start_s?: number;
  end_s?: number;
  genres?: string | null;
};

export type PublishOptions = {
  festival?: string | null;
  venue?: string | null;
  year?: number | null;
};

export type BulkPublishRequest = {
  segment_ids: number[];
  festival?: string | null;
  venue?: string | null;
  year?: number | null;
};

export type BulkPublishItemResult = {
  segment_id: number;
  status: "published" | "failed";
  error: string | null;
};

export type BulkPublishResponse = {
  results: BulkPublishItemResult[];
  succeeded: number;
  failed: number;
};

export const segmentsApi = {
  list: (recordingId: number) =>
    api.get<Segment[]>(`/api/segments?recording_id=${recordingId}`),
  create: (p: SegmentCreate) => api.post<Segment>("/api/segments", p),
  patch: (id: number, p: SegmentPatch) => api.patch<Segment>(`/api/segments/${id}`, p),
  delete: (id: number) => api.delete<void>(`/api/segments/${id}`),
  publish: (id: number, opts: PublishOptions) =>
    api.post<Segment>(`/api/segments/${id}/publish`, opts),
  bulkPublish: (p: BulkPublishRequest) =>
    api.post<BulkPublishResponse>("/api/segments/bulk-publish", p),
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

// ── Auth ────────────────────────────────────────────────────────────────────

export type SessionState = {
  authenticated: boolean;
  password_set: boolean;
};

export const authApi = {
  me: () => api.get<SessionState>("/api/auth/me"),
  login: async (password: string) => {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ password }),
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, body);
    }
  },
  logout: async () => {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  },
  setPassword: async (newPassword: string, currentPassword?: string) => {
    const res = await fetch("/api/auth/set-password", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        new_password: newPassword,
        current_password: currentPassword ?? null,
      }),
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, body);
    }
  },
};

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

// ── Channel Watchers ────────────────────────────────────────────────────────

export type VodSegmentationMode = "chapters" | "whole-video" | "manual";

export type ChannelWatcher = {
  id: number;
  channel_url: string;
  channel_name: string;
  avatar_url: string | null;
  title_filter: string | null;
  quality_cap: string | null;
  retention_days: number;
  enabled: boolean;
  last_polled: string | null;
  last_live_id: string | null;
  added_at: string;
  // VOD fields (v0.3)
  watch_live: boolean;
  watch_vod_uploads: boolean;
  vod_title_filter: string | null;
  vod_artist_regex: string | null;
  vod_segmentation_mode: VodSegmentationMode;
  default_genres: string | null;
  auto_publish: boolean;
  extract_setlist_from_comments: boolean;
  extract_setlist_from_setlistfm: boolean;
  auto_delete_source_after_publish: boolean | null;
};

export type ChannelWatcherCreate = {
  channel_url: string;
  title_filter?: string | null;
  quality_cap?: string | null;
  retention_days?: number;
  watch_live?: boolean;
  watch_vod_uploads?: boolean;
  auto_publish?: boolean;
};

export type ChannelWatcherPatch = {
  title_filter?: string | null;
  quality_cap?: string | null;
  retention_days?: number;
  enabled?: boolean;
  // VOD fields (v0.3)
  watch_live?: boolean;
  watch_vod_uploads?: boolean;
  vod_title_filter?: string | null;
  vod_artist_regex?: string | null;
  vod_segmentation_mode?: VodSegmentationMode;
  default_genres?: string | null;
  auto_publish?: boolean;
  extract_setlist_from_comments?: boolean;
  extract_setlist_from_setlistfm?: boolean;
  auto_delete_source_after_publish?: boolean | null;
};

export const watchersApi = {
  list: () => api.get<ChannelWatcher[]>("/api/channel-watchers"),
  get: (id: number) => api.get<ChannelWatcher>(`/api/channel-watchers/${id}`),
  create: (p: ChannelWatcherCreate) => api.post<ChannelWatcher>("/api/channel-watchers", p),
  patch: (id: number, p: ChannelWatcherPatch) =>
    api.patch<ChannelWatcher>(`/api/channel-watchers/${id}`, p),
  delete: (id: number) => api.delete<void>(`/api/channel-watchers/${id}`),
  getBacklogStatus: (watcherId: number) =>
    api.get<BacklogCacheState>(`/api/channel-watchers/${watcherId}/backlog/status`),
  refreshBacklog: (watcherId: number) =>
    api.post<{ status: string; started: boolean }>(
      `/api/channel-watchers/${watcherId}/backlog/refresh`,
      {},
    ),
};

// ── Backlog ──────────────────────────────────────────────────────────────────

export type BacklogCacheStatus =
  | "never_fetched"
  | "fetching"
  | "complete"
  | "error"
  | "cancelled";

export interface BacklogCacheState {
  status: BacklogCacheStatus;
  fetched_at: string | null;
  total_count: number;
  progress_pct: number;
  error: string | null;
  stale: boolean;
}

export type BacklogItemState = "downloaded" | "queued" | "not_downloaded";

export type BacklogItem = {
  youtube_id: string;
  title: string;
  url: string;
  thumbnail_url: string | null;
  upload_date: string | null;
  duration_s: number | null;
  view_count: number | null;
  like_count: number | null;
  state: BacklogItemState;
};

// ── Smart-paste / probe response shapes ─────────────────────────────────────

export type ProbeChannelResult = {
  type: "channel";
  channel_name: string;
  avatar_url: string | null;
  url: string;
};

export interface ProbePlaylistItem {
  youtube_id: string;
  title: string;
  channel_name: string | null;
  is_already_known: boolean;
  duration_s: number | null;
  upload_date: string | null;
  thumbnail_url: string | null;
}

export type ProbePlaylistResult = {
  type: "playlist";
  playlist_id: string;
  playlist_title: string;
  count: number;
  items: ProbePlaylistItem[];
};

// A Stream-like result (kind=live or kind=video) is just a Stream object.
// Backend may also return detected_setlist_source on the object.
export type ProbeStreamResult = Stream & {
  detected_setlist_source?: string | null;
};

export type ProbeResult = ProbeStreamResult | ProbeChannelResult | ProbePlaylistResult;

// ── Playlist ingest ──────────────────────────────────────────────────────────

export type PlaylistIngestConfirm = {
  video_ids: string[];
};

export const playlistApi = {
  confirm: (p: PlaylistIngestConfirm) =>
    api.post<{ queued_recording_ids: number[] }>("/api/playlists/ingest/confirm", p),
};
