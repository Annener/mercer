import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, HttpError } from '@/api/client';
import { showToast } from '@/components/ui';
import type { CampaignId, CreateStateFieldRequest, StateFieldConfig } from '@/api/types';

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidUuid(value: string | null | undefined): value is string {
  return typeof value === 'string' && UUID_REGEX.test(value);
}

function invalidUuidError(): HttpError {
  return new HttpError(
    400,
    { code: 'invalid_field_id' },
    'Некорректный ID поля',
  );
}

function warnInvalidUuid(action: string, value: unknown): void {
  console.warn(
    `[useStateFields] ${action}: invalid or missing field_id`,
    { value },
  );
  showToast('danger', 'Некорректный ID поля — действие отменено');
}

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
    mutationFn: ({ fieldId, data }: { fieldId: string; data: Partial<StateFieldConfig> }) => {
      if (!isValidUuid(fieldId)) {
        return Promise.reject(invalidUuidError());
      }
      return api.updateStateField(campaignId, fieldId, data);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['state-fields', campaignId] }),
    onError: (err) => {
      console.error('[useStateFields] update failed', err);
      if (err instanceof HttpError) {
        showToast('danger', `Не удалось обновить поле: ${err.message}`);
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (fieldId: string) => {
      // Defensive: не отправляем запрос с невалидным ID, иначе бэкенд вернёт 500
      // (uuid.UUID() падает на невалидной строке).
      if (!isValidUuid(fieldId)) {
        return Promise.reject(invalidUuidError());
      }
      return api.deleteStateField(campaignId, fieldId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['state-fields', campaignId] });
      showToast('success', 'Поле удалено');
    },
    onError: (err) => {
      console.error('[useStateFields] delete failed', err);
      // На 400/404 — убираем висячее поле из кэша.
      if (err instanceof HttpError && (err.status === 400 || err.status === 404)) {
        void queryClient.invalidateQueries({ queryKey: ['state-fields', campaignId] });
      }
      if (err instanceof HttpError) {
        showToast('danger', `Не удалось удалить поле: ${err.message}`);
      }
    },
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
    toggleEnabled: (fieldId: string, enabled: boolean) => {
      if (!isValidUuid(fieldId)) {
        warnInvalidUuid('toggleEnabled', fieldId);
        return;
      }
      updateMutation.mutate({ fieldId, data: { enabled } });
    },
    update: (fieldId: string, data: Partial<StateFieldConfig>) => {
      if (!isValidUuid(fieldId)) {
        warnInvalidUuid('update', fieldId);
        return;
      }
      updateMutation.mutate({ fieldId, data });
    },
    remove: (fieldId: string) => {
      if (!isValidUuid(fieldId)) {
        warnInvalidUuid('remove', fieldId);
        return;
      }
      if (confirm('Удалить поле? Это очистит значение в активной версии state.')) {
        deleteMutation.mutate(fieldId);
      }
    },
    reorder: (orderedIds: string[]) => reorderMutation.mutate(orderedIds),
  };
}