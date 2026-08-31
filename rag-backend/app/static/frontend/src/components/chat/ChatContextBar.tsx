import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useChatStore } from '@/stores';
import { api } from '@/api/client';
import { UpdateModeStartModal } from '@/components/wizard/UpdateModeStartModal';
import { PendingIndexBanner } from './PendingIndexBanner';
import type { Pipeline, PipelineId } from '@/api/types';

const PIPELINE_NONE_ID = '__none__';

export function ChatContextBar() {
  const queryClient = useQueryClient();
  const currentChatId = useChatStore((s) => s.currentChatId);
  const currentChat = useChatStore((s) => s.currentChat);
  const reloadChat = useChatStore((s) => s.loadChat);
  const [updateModeOpen, setUpdateModeOpen] = useState(false);

  const pipelinesQuery = useQuery({
    queryKey: ['pipelines', currentChat?.domain_id, currentChat?.campaign_id ?? null],
    queryFn: () => api.getPipelines(currentChat!.domain_id, currentChat!.campaign_id ?? null),
    enabled: !!currentChat?.domain_id,
    staleTime: 30_000,
  });

  const pipelines: Pipeline[] = (pipelinesQuery.data ?? []).filter((p) => p.is_active);

  const lockMutation = useMutation({
    mutationFn: async (pipelineId: PipelineId | null) => {
      if (!currentChatId) throw new Error('No chat selected');
      return api.lockPipeline(currentChatId, pipelineId);
    },
    onSuccess: async () => {
      if (!currentChatId) return;
      await reloadChat(currentChatId);
      void queryClient.invalidateQueries({ queryKey: ['chat', currentChatId] });
    },
  });

  const fullDocMutation = useMutation({
    mutationFn: async (enabled: boolean) => {
      if (!currentChatId) throw new Error('No chat selected');
      return api.setFullDocMode(currentChatId, enabled, currentChat?.campaign_id ?? null);
    },
    onSuccess: async () => {
      if (!currentChatId) return;
      await reloadChat(currentChatId);
    },
    onError: () => {
      setFullDocLocal((prev) => !prev);
    },
  });

  const contextUpdateMutation = useMutation({
    mutationFn: async (enabled: boolean) => {
      if (!currentChatId) throw new Error('No chat selected');
      return api.setContextUpdateMode(currentChatId, enabled, currentChat?.campaign_id ?? null);
    },
    onSuccess: async () => {
      if (!currentChatId) return;
      await reloadChat(currentChatId);
    },
    onError: () => {
      setContextUpdateLocal((prev) => !prev);
    },
  });

  const ragPrefillMutation = useMutation({
    mutationFn: async (enabled: boolean) => {
      if (!currentChatId) throw new Error('No chat selected');
      return api.setRagPrefill(currentChatId, enabled, currentChat?.campaign_id ?? null);
    },
    onSuccess: async () => {
      if (!currentChatId) return;
      await reloadChat(currentChatId);
    },
    onError: () => {
      setRagPrefillLocal((prev) => !prev);
    },
  });

  const [fullDocLocal, setFullDocLocal] = useState<boolean>(Boolean(currentChat?.full_document_mode_enabled));

  useEffect(() => {
    setFullDocLocal(Boolean(currentChat?.full_document_mode_enabled));
  }, [currentChat?.full_document_mode_enabled]);

  const [contextUpdateLocal, setContextUpdateLocal] = useState<boolean>(
    Boolean(currentChat?.context_update_mode),
  );

  useEffect(() => {
    setContextUpdateLocal(Boolean(currentChat?.context_update_mode));
  }, [currentChat?.context_update_mode]);

  const [ragPrefillLocal, setRagPrefillLocal] = useState<boolean>(
    Boolean(currentChat?.rag_prefill_enabled),
  );

  useEffect(() => {
    setRagPrefillLocal(Boolean(currentChat?.rag_prefill_enabled));
  }, [currentChat?.rag_prefill_enabled]);

  // Не рендерим контекст-бар без активного чата
  if (!currentChatId || !currentChat) return null;

  const lockedPipelineId = (currentChat.locked_pipeline_id as PipelineId | null | undefined) ?? null;
  const hasCampaign = Boolean(currentChat.campaign_id);

  const effectiveSelected = lockedPipelineId ?? '';

  const showLockedHidden = (() => {
    if (!lockedPipelineId) return null;
    const exists = pipelines.some((p) => p.pipeline_id === lockedPipelineId);
    if (exists) return null;
    return lockedPipelineId;
  })();

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border bg-surface-2/40 px-4 py-2 text-xs">
        {/* Pipeline selector */}
        <div className="flex items-center gap-1.5">
          <span className="font-medium text-text-muted">Пайплайн:</span>
          <select
            className="rounded border border-border bg-surface px-2 py-1 text-xs focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/20 disabled:opacity-60"
            value={effectiveSelected}
            disabled={!!lockedPipelineId}
            onChange={(e) => {
              const v = e.target.value;
              const pipelineId: PipelineId | null = v === '' ? null : (v as PipelineId);
              lockMutation.mutate(pipelineId);
            }}
          >
            <option value="">Авто</option>
            <option value={PIPELINE_NONE_ID}>— Без пайплайна —</option>
            {pipelines.map((p) => (
              <option key={p.pipeline_id} value={p.pipeline_id}>
                {p.name}
              </option>
            ))}
            {showLockedHidden && (
              <option value={showLockedHidden}>{showLockedHidden}</option>
            )}
          </select>
          <button
            type="button"
            onClick={() => lockMutation.mutate(lockedPipelineId ? null : effectiveSelected || null)}
            disabled={lockMutation.isPending || (!lockedPipelineId && !effectiveSelected)}
            aria-label={lockedPipelineId ? 'Разблокировать пайплайн' : 'Зафиксировать пайплайн'}
            title={
              lockedPipelineId
                ? 'Пайплайн зафиксирован. Нажмите, чтобы отменить.'
                : 'Нажмите, чтобы зафиксировать выбранный пайплайн'
            }
            className={`inline-flex h-7 w-7 items-center justify-center rounded border transition ${
              lockedPipelineId
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border bg-surface text-text-muted hover:bg-surface-2'
            }`}
          >
            {lockedPipelineId ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 9.9-1" />
              </svg>
            )}
          </button>
        </div>

        <div className="h-4 w-px bg-border" />

        {/* RAG prefill toggle (per-chat master switch). */}
        {/* When ON, evidence is pre-pended to system_prompt and round 0 forces
            a tool call (legacy grounded behaviour). When OFF, the model only
            sees the conversation and decides itself whether to call
            search_knowledge. Full Document Mode is only available when this
            is enabled (it relies on the up-front retrieval to propose docs). */}
        <label
          className="flex cursor-pointer items-center gap-1.5 select-none"
          title="Если включено — модель получит выборку из базы знаний сразу и обязана её использовать. Если выключено — модель сама решает, нужен ли поиск."
        >
          <input
            type="checkbox"
            checked={ragPrefillLocal}
            onChange={(e) => {
              const v = e.target.checked;
              setRagPrefillLocal(v);
              ragPrefillMutation.mutate(v);
            }}
            disabled={ragPrefillMutation.isPending}
            className="h-3.5 w-3.5 cursor-pointer accent-primary"
          />
          <span className="inline-flex items-center gap-1 text-text">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            Подмешивать RAG
          </span>
        </label>

        {/* Full Document Mode toggle — visible only when rag_prefill is on. */}
        {ragPrefillLocal && (
          <>
            <label
              className="flex cursor-pointer items-center gap-1.5 select-none"
              title="Разрешить отправку полных документов (требует включённого Подмешивать RAG)"
            >
              <input
                type="checkbox"
                checked={fullDocLocal}
                onChange={(e) => {
                  const v = e.target.checked;
                  setFullDocLocal(v);
                  fullDocMutation.mutate(v);
                }}
                disabled={fullDocMutation.isPending}
                className="h-3.5 w-3.5 cursor-pointer accent-primary"
              />
              <span className="inline-flex items-center gap-1 text-text">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
                Полные документы
              </span>
            </label>
          </>
        )}

        {/* Context Update Mode toggle */}
        {hasCampaign && (
          <>
            <div className="h-4 w-px bg-border" />
            <label
              className="flex cursor-pointer items-center gap-1.5 select-none"
              title="Разрешить модели предлагать изменения Campaign State и файлов контекста"
            >
              <input
                type="checkbox"
                checked={contextUpdateLocal}
                onChange={(e) => {
                  const v = e.target.checked;
                  setContextUpdateLocal(v);
                  contextUpdateMutation.mutate(v);
                }}
                disabled={contextUpdateMutation.isPending}
                className="h-3.5 w-3.5 cursor-pointer accent-primary"
              />
              <span className="inline-flex items-center gap-1 text-text">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>
                Авто-обновление контекста
              </span>
            </label>
          </>
        )}

        <div className="h-4 w-px bg-border" />

        {/* Update Mode button (только для чатов с кампанией) */}
        {hasCampaign && (
          <button
            type="button"
            onClick={() => setUpdateModeOpen(true)}
            className="inline-flex items-center gap-1 rounded border border-border bg-surface px-2 py-1 text-xs font-medium text-text hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            title="Обновить документы контекста"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polyline points="23 4 23 10 17 10" />
              <polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            Обновить контекст
          </button>
        )}

        {/* Pending files banner — справа в строке */}
        <div className="ml-auto">
          <PendingIndexBanner domainId={currentChat.domain_id} />
        </div>
      </div>

      <UpdateModeStartModal
        open={updateModeOpen}
        onClose={() => setUpdateModeOpen(false)}
        chatId={currentChatId}
      />
    </>
  );
}
