import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { CampaignId, CreateStateFieldRequest, StateFieldConfig } from '@/api/types';

export function useStateFields(campaignId: CampaignId) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['state-fields', campaignId],
    queryFn: () => api.getStateFields(campaignId),
  });

  const createMutation = useMutation({
    mutationFn: (data: CreateStateFieldRequest) => api.createStateField(campaignId, data),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['state-fields', campaignId] }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ fieldId, data }: { fieldId: string; data: Partial<StateFieldConfig> }) =>
      api.updateStateField(campaignId, fieldId, data),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['state-fields', campaignId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (fieldId: string) => api.deleteStateField(campaignId, fieldId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['state-fields', campaignId] }),
  });

  const reorderMutation = useMutation({
    mutationFn: (orderedIds: string[]) => api.reorderStateFields(campaignId, orderedIds),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['state-fields', campaignId] }),
  });

  return {
    list: query.data ?? [],
    loading: query.isLoading,
    error: query.error,
    create: (data: CreateStateFieldRequest) => createMutation.mutate(data),
    toggleEnabled: (fieldId: string, enabled: boolean) =>
      updateMutation.mutate({ fieldId, data: { enabled } }),
    update: (fieldId: string, data: Partial<StateFieldConfig>) =>
      updateMutation.mutate({ fieldId, data }),
    remove: (fieldId: string) => {
      if (confirm('Удалить поле? Это очистит значение в активной версии state.')) {
        deleteMutation.mutate(fieldId);
      }
    },
    reorder: (orderedIds: string[]) => reorderMutation.mutate(orderedIds),
  };
}