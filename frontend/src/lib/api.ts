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
