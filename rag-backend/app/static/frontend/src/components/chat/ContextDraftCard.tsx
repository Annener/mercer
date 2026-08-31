import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui';
import { api } from '@/api/client';
import { useChatStore } from '@/stores';
import type { ContextDraft, UUID } from '@/api/types';

interface Props {
  chatId: UUID;
  draft: ContextDraft;
  onClose: () => void;
}

export function ContextDraftCard({ chatId, draft, onClose }: Props) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const opsCount = draft.state_patch.length;

  const acceptMutation = useMutation({
    mutationFn: () => api.acceptContextDraft(chatId),
    onMutate: () => {
      setActionError(null);
      void queryClient.setQueryData(['context-draft', chatId], { draft: null });
      void queryClient.cancelQueries({ queryKey: ['context-draft', chatId] });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['context-draft', chatId] });
      void queryClient.invalidateQueries({ queryKey: ['chat', chatId] });
      void queryClient.invalidateQueries({ queryKey: ['campaign-state-version'] });
      void useChatStore.getState().loadChat(chatId);
      onClose();
    },
    onError: (err: unknown) => {
      // Восстанавливаем UI через refetch — setQueryData выше оптимистично стёр
      void queryClient.invalidateQueries({ queryKey: ['context-draft', chatId] });
      const msg = err instanceof Error ? err.message : String(err);
      setActionError(msg);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () => api.rejectContextDraft(chatId),
    onMutate: () => {
      setActionError(null);
      void queryClient.setQueryData(['context-draft', chatId], { draft: null });
      void queryClient.cancelQueries({ queryKey: ['context-draft', chatId] });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['context-draft', chatId] });
      onClose();
    },
    onError: (err: unknown) => {
      void queryClient.invalidateQueries({ queryKey: ['context-draft', chatId] });
      const msg = err instanceof Error ? err.message : String(err);
      setActionError(msg);
    },
  });

  const checkFilesMutation = useMutation({
    mutationFn: () => api.checkFilesFromContextDraft(chatId),
    onError: (err: unknown) => {
      // Phase 4: 501 — сообщаем пользователю явно, не молчим.
      const msg = err instanceof Error ? err.message : String(err);
      setActionError(
        msg.includes('501') || msg.toLowerCase().includes('phase_5')
          ? 'Проверка файлов будет доступна в следующей фазе (Phase 5).'
          : msg,
      );
    },
  });

  return (
    <div
      role="region"
      aria-label="Возможные обновления контекста"
      className="rounded-lg border border-amber-300 bg-amber-50 p-4 shadow-sm dark:border-amber-700 dark:bg-amber-900/20"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-amber-900 dark:text-amber-100">
            Контекст требует обновления ({opsCount}{' '}
            {pluralizeOps(opsCount)})
          </h3>
          {draft.summary && (
            <p className="mt-1 text-sm text-amber-800 dark:text-amber-200">
              {draft.summary}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Скрыть"
          className="text-amber-700 hover:text-amber-900 dark:text-amber-300 dark:hover:text-amber-100"
        >
          ×
        </button>
      </div>

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="mt-2 text-sm text-amber-700 underline hover:text-amber-900 dark:text-amber-300 dark:hover:text-amber-100"
      >
        {expanded ? 'Скрыть детали' : 'Показать детали'}
      </button>

      {expanded && (
        <ul className="mt-2 space-y-2 text-sm">
          {draft.state_patch.map((op, i) => (
            <li
              key={i}
              className="border-l-2 border-amber-300 bg-white/40 px-2 py-1 dark:bg-black/20"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded bg-amber-200 px-1.5 py-0.5 font-mono text-xs text-amber-900 dark:bg-amber-800 dark:text-amber-100">
                  {op.type}
                </span>
                <span className="font-mono text-xs text-amber-800 dark:text-amber-200">
                  {op.field_key}
                  {op.item_key ? `.${op.item_key}` : ''}
                </span>
              </div>
              {op.text && (
                <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                  {op.text}
                </div>
              )}
              {op.reason && (
                <div className="mt-1 text-xs italic text-amber-600 dark:text-amber-400">
                  {op.reason}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {actionError && (
        <div
          role="alert"
          className="mt-3 rounded border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-700 dark:border-red-700 dark:bg-red-900/20 dark:text-red-300"
        >
          {actionError}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          onClick={() => acceptMutation.mutate()}
          loading={acceptMutation.isPending}
          variant="primary"
          size="sm"
        >
          Применить
        </Button>
        <Button
          onClick={() => rejectMutation.mutate()}
          loading={rejectMutation.isPending}
          variant="ghost"
          size="sm"
        >
          Отклонить
        </Button>
        <Button
          onClick={() => checkFilesMutation.mutate()}
          loading={checkFilesMutation.isPending}
          variant="ghost"
          size="sm"
        >
          Применить и проверить файлы
        </Button>
      </div>
    </div>
  );
}

export function useContextDraftQuery(chatId: UUID | null) {
  return useQuery({
    queryKey: ['context-draft', chatId],
    queryFn: () => api.getContextDraft(chatId as UUID),
    enabled: !!chatId,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
    staleTime: 10_000,
  });
}

function pluralizeOps(n: number): string {
  const mod100 = n % 100;
  const mod10 = n % 10;
  if (mod100 >= 11 && mod100 <= 19) return 'операций';
  if (mod10 === 1) return 'операция';
  if (mod10 >= 2 && mod10 <= 4) return 'операции';
  return 'операций';
}
