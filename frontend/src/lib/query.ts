import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { settingsApi, type Settings, type SettingsPatch } from "./api";

export const keys = {
  settings: ["settings"] as const,
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
