import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { settingsApi, type Settings, type SettingsPatch } from "./api";
import {
  type Recording,
  type Stream,
  type WatchSubscription,
  type WatchSubscriptionPatch,
  recordingsApi,
  streamsApi,
  watchApi,
} from "./api";

export const keys = {
  settings: ["settings"] as const,
  streams: ["streams"] as const,
  stream: (id: number) => ["streams", id] as const,
  watch: (id: number) => ["streams", id, "watch"] as const,
  recordings: (streamId?: number) =>
    streamId !== undefined ? (["recordings", streamId] as const) : (["recordings"] as const),
};

export function useSettings() {
  return useQuery<Settings>({
    queryKey: keys.settings,
    queryFn: () => settingsApi.get(),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation<Settings, Error, SettingsPatch>({
    mutationFn: (patch) => settingsApi.patch(patch),
    onSuccess: (data) => qc.setQueryData(keys.settings, data),
  });
}

export function useStreams() {
  return useQuery<Stream[]>({
    queryKey: keys.streams,
    queryFn: () => streamsApi.list(),
  });
}

export function useStream(id: number) {
  return useQuery<Stream>({
    queryKey: keys.stream(id),
    queryFn: () => streamsApi.get(id),
  });
}

export function useAddStream() {
  const qc = useQueryClient();
  return useMutation<Stream, Error, string>({
    mutationFn: (url) => streamsApi.create(url),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.streams }),
  });
}

export function useDeleteStream() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => streamsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.streams }),
  });
}

export function useWatchSubscription(streamId: number, enabled: boolean = true) {
  return useQuery<WatchSubscription | null>({
    queryKey: keys.watch(streamId),
    queryFn: async () => {
      try {
        return await watchApi.get(streamId);
      } catch (e) {
        if ((e as { status?: number }).status === 404) return null;
        throw e;
      }
    },
    enabled,
  });
}

export function useToggleWatch(streamId: number) {
  const qc = useQueryClient();
  return useMutation<WatchSubscription, Error, WatchSubscriptionPatch>({
    mutationFn: (p) => watchApi.patch(streamId, p),
    onSuccess: (data) => {
      qc.setQueryData(keys.watch(streamId), data);
      qc.invalidateQueries({ queryKey: keys.streams });
    },
  });
}

export function useRecordings(streamId?: number) {
  return useQuery<Recording[]>({
    queryKey: keys.recordings(streamId),
    queryFn: () => recordingsApi.list(streamId),
  });
}

import {
  type Schedule,
  type ScheduleCreate,
  type SchedulePatch,
  schedulesApi,
} from "./api";

export const schedulesKeys = {
  all: ["schedules"] as const,
  one: (id: number) => ["schedules", id] as const,
};

export function useSchedules() {
  return useQuery<Schedule[]>({
    queryKey: schedulesKeys.all,
    queryFn: () => schedulesApi.list(),
    refetchInterval: 30_000,
  });
}

export function useCreateSchedule() {
  const qc = useQueryClient();
  return useMutation<Schedule, Error, ScheduleCreate>({
    mutationFn: (p) => schedulesApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: schedulesKeys.all }),
  });
}

export function useUpdateSchedule(id: number) {
  const qc = useQueryClient();
  return useMutation<Schedule, Error, SchedulePatch>({
    mutationFn: (p) => schedulesApi.patch(id, p),
    onSuccess: () => qc.invalidateQueries({ queryKey: schedulesKeys.all }),
  });
}

export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => schedulesApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: schedulesKeys.all }),
  });
}

import {
  api,
  type Segment,
  type SegmentCreate,
  type SegmentPatch,
  type PublishOptions,
  segmentsApi,
} from "./api";

export const segmentsKeys = {
  forRecording: (rid: number) => ["segments", rid] as const,
};

export function useSegments(recordingId: number) {
  return useQuery<Segment[]>({
    queryKey: segmentsKeys.forRecording(recordingId),
    queryFn: () => segmentsApi.list(recordingId),
  });
}

export function useCreateSegment(recordingId: number) {
  const qc = useQueryClient();
  return useMutation<Segment, Error, SegmentCreate>({
    mutationFn: (p) => segmentsApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: segmentsKeys.forRecording(recordingId) }),
  });
}

export function useUpdateSegment(recordingId: number) {
  const qc = useQueryClient();
  return useMutation<Segment, Error, { id: number; patch: SegmentPatch }>({
    mutationFn: ({ id, patch }) => segmentsApi.patch(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: segmentsKeys.forRecording(recordingId) }),
  });
}

export function useDeleteSegment(recordingId: number) {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => segmentsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: segmentsKeys.forRecording(recordingId) }),
  });
}

export function usePublishSegment(recordingId: number) {
  const qc = useQueryClient();
  return useMutation<Segment, Error, { id: number; options: PublishOptions }>({
    mutationFn: ({ id, options }) => segmentsApi.publish(id, options),
    onSuccess: () => qc.invalidateQueries({ queryKey: segmentsKeys.forRecording(recordingId) }),
  });
}

export function usePublishedSegments() {
  return useQuery<Segment[]>({
    queryKey: ["segments", "published"],
    queryFn: () => api.get<Segment[]>("/api/segments?status=published"),
  });
}

import {
  type ChannelWatcher,
  type ChannelWatcherCreate,
  type ChannelWatcherPatch,
  type BacklogItem,
  watchersApi,
} from "./api";

export const watchersKeys = {
  all: ["channel-watchers"] as const,
  one: (id: number) => ["channel-watchers", id] as const,
  backlog: (id: number, sort: string, offset: number) =>
    ["backlog", id, sort, offset] as const,
};

export function useChannelWatchers() {
  return useQuery<ChannelWatcher[]>({
    queryKey: watchersKeys.all,
    queryFn: () => watchersApi.list(),
    refetchInterval: 60_000,
  });
}

export function useChannelWatcher(id: number) {
  return useQuery<ChannelWatcher>({
    queryKey: watchersKeys.one(id),
    queryFn: () => watchersApi.get(id),
  });
}

export function useCreateChannelWatcher() {
  const qc = useQueryClient();
  return useMutation<ChannelWatcher, Error, ChannelWatcherCreate>({
    mutationFn: (p) => watchersApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: watchersKeys.all }),
  });
}

export function useUpdateChannelWatcher() {
  const qc = useQueryClient();
  return useMutation<ChannelWatcher, Error, { id: number; patch: ChannelWatcherPatch }>({
    mutationFn: ({ id, patch }) => watchersApi.patch(id, patch),
    onSuccess: (data, { id }) => {
      qc.invalidateQueries({ queryKey: watchersKeys.all });
      qc.setQueryData(watchersKeys.one(id), data);
    },
  });
}

export function useDeleteChannelWatcher() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => watchersApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: watchersKeys.all }),
  });
}

export function useWatcherBacklog(watcherId: number, sort = "newest", offset = 0) {
  return useQuery<BacklogItem[]>({
    queryKey: watchersKeys.backlog(watcherId, sort, offset),
    queryFn: () =>
      api.get<BacklogItem[]>(
        `/api/channel-watchers/${watcherId}/backlog?sort=${sort}&offset=${offset}`,
      ),
  });
}

import { type SessionState, authApi } from "./api";

export function useSession() {
  return useQuery<SessionState>({
    queryKey: ["auth", "me"],
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 30_000,
  });
}
