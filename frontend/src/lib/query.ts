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
