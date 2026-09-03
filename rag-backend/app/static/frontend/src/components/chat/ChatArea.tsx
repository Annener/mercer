import { useEffect, useState, useRef, useCallback, type KeyboardEvent } from 'react';
import { STATUS_DEBOUNCE_MS, useDebouncedStatus } from '@/hooks/useDebouncedStatus';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Card } from '@/components/ui';
import { useChatStore, useDomainStore, useThemeStore } from '@/stores';
import { api } from '@/api/client';
import { Markdown } from './Markdown';
import { ChatContextBar } from './ChatContextBar';
import { ModelHealthIndicator } from '@/components/system';
import { UpdateModePanel } from '@/components/wizard/UpdateModePanel';
import {
  PipelineConfirmCard,
  ValidationCard,
} from '@/components/chat/cards/PipelineCards';
import { FullDocPanel, type FullDocCandidate } from '@/components/chat/cards/FullDocPanel';
import { ToolCallCard, type ToolCallInfo, type ToolResultInfo } from '@/components/chat/cards/ToolCallCard';
import { ProposalCard } from '@/components/chat/cards/ProposalCard';
import { ContextDraftCard, useContextDraftQuery } from './ContextDraftCard';
import { DriftStatusPopup } from './DriftStatusPopup';
import {
  PipelineProgress,
  PipelineBadge,
  PipelineStatusLine,
} from '@/components/chat/cards/PipelineExtras';
import type { ChatMessage, Source } from '@/api/types';

type InlineItem =
  | { kind: 'confirm'; confirmToken: string; pipelineName: string; reasoning?: string }
  | { kind: 'validation'; resumeToken: string; stepName: string; content?: string; options?: string[] }
  | { kind: 'fulldoc'; chatId: string; candidates: FullDocCandidate[] }
  | { kind: 'tool_call'; round: number; info: ToolCallInfo }
  | { kind: 'proposal'; round: number; summary: string; fieldChangesCount: number; statePatchCount: number; fileChangesCount: number }
  | { kind: 'progress'; step: number; total: number; stepName?: string; doneSteps: number[] }
  | { kind: 'pipeline_badge'; pipelineName?: string; mode?: string }
  | { kind: 'pipeline_status'; type: 'pipeline_resumed' | 'pipeline_cancelled'; preview?: string; stepName?: string };

type ToolsState = Record<number, ToolCallInfo>;
type ToolsResultsState = Record<number, ToolResultInfo>;

export function ChatArea() {
  const currentChatId = useChatStore((s) => s.currentChatId);
  const currentChat = useChatStore((s) => s.currentChat);
  const messages = useChatStore((s) => s.messages);
  const appendMessage = useChatStore((s) => s.appendMessage);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const setStreaming = useChatStore((s) => s.setStreaming);
  const setStreamingContent = useChatStore((s) => s.setStreamingContent);
  const showUpdateModePanel = useChatStore((s) => s.showUpdateModePanel);
  const setShowUpdateModePanel = useChatStore((s) => s.setShowUpdateModePanel);

  const draftQuery = useContextDraftQuery(currentChatId);
  const draft = draftQuery.data?.draft ?? null;
  const [showContextDraftCard, setShowContextDraftCard] = useState(true);
  useEffect(() => {
    setShowContextDraftCard(true);
  }, [draft?.drift_hash]);

  const currentDomainId = useDomainStore((s) => s.currentDomainId);
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);

  const paramsQuery = useQuery({
    queryKey: ['settings-params'],
    queryFn: () => api.getSettingsParams(),
    staleTime: 60_000,
  });
  const streamEnabled = (() => {
    const v = paramsQuery.data?.find((p) => p.key === 'chat.stream_answers')?.value;
    return v === true || v === 'true' || v === undefined;
  })();

  const [input, setInput] = useState('');
  const [streamedText, setStreamedText] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { displayed: debouncedProcessingText, push: pushStatus, clear: clearStatus } =
    useDebouncedStatus(STATUS_DEBOUNCE_MS);
  // `processingText` рендерится в <ProcessingStatus>.
  const processingText: string | null = debouncedProcessingText;

  // Back-compat обёртка: ВСЕ существующие callsites `setProcessingText(t)`
  // роутятся через debouncer. `setProcessingText(null)` сбрасывает
  // сразу (и pending, и displayed).
  const setProcessingText = useCallback(
    (next: string | null) => {
      if (next === null) clearStatus();
      else pushStatus(next);
    },
    [pushStatus, clearStatus],
  );
  const [inlines, setInlines] = useState<InlineItem[]>([]);
  const [, setTools] = useState<ToolsState>({});
  const [toolsResults, setToolsResults] = useState<ToolsResultsState>({});
  const [lastProposalRound, setLastProposalRound] = useState<number | null>(null);
  const queryClient = useQueryClient();

  // Тип для nested stream, возвращаемого confirm/resume/fulldoc — обрабатываем так же, как внешний стрим
  const handleNestedStream = useCallback(
    async (
      stream: ReadableStream<Uint8Array> | unknown,
    ): Promise<{ streamedText: string; sources: Source[] } | undefined> => {
      if (!(stream instanceof ReadableStream)) return undefined;
      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let acc = '';
      const sourcesAcc: Source[] = [];
      const sourcesSeen = new Set<string>();
      const addSources = (raw: unknown) => {
        if (!Array.isArray(raw)) return;
        for (const s of raw) {
          if (!s || typeof s !== 'object') continue;
          const src = s as Source;
          const key = `${src.path ?? ''}#${src.page ?? ''}`;
          if (sourcesSeen.has(key)) continue;
          sourcesSeen.add(key);
          sourcesAcc.push(src);
        }
      };
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6).trim();
          if (data === '[DONE]') continue;
          try {
            const parsed = JSON.parse(data) as Record<string, unknown>;
            const type = parsed.type as string | undefined;
            if (type === 'token' && typeof parsed.content === 'string') {
              acc += parsed.content;
              setStreamedText(acc);
              setProcessingText(null);
            } else if (type === 'step_status' && typeof parsed.text === 'string') {
              setProcessingText(parsed.text);
            } else if (type === 'sources') {
              addSources(parsed.sources);
            } else if (type === 'tool_result') {
              addSources(parsed.sources);
            }
          } catch {
            /* ignore */
          }
        }
      }
      return { streamedText: acc, sources: sourcesAcc };
    },
    [setProcessingText],
  );

  const removeInline = (predicate: (item: InlineItem) => boolean) => {
    setInlines((prev) => prev.filter((it) => !predicate(it)));
  };

  // Smart scroll: пользователь отлистал вверх → блокируем auto-scroll
  useEffect(() => {
    const el = messagesContainerRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance =
        el.scrollHeight - el.scrollTop - el.clientHeight;
      userScrolledUpRef.current = distance > 120;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Auto-scroll to bottom when new messages arrive (с учётом флага)
  useEffect(() => {
    if (userScrolledUpRef.current) return;
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamedText, inlines, processingText]);

  // Auto-grow textarea to fit content up to ~33vh, then scroll inside.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const maxHeight = window.innerHeight / 3;
    const nextHeight = Math.min(el.scrollHeight, maxHeight);
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }, [input]);

  const sendMutation = useMutation({
    mutationFn: async ({ content, signal }: { content: string; signal?: AbortSignal }) => {
      if (!currentChatId) throw new Error('No chat selected');
      setStreaming(true);
      setStreamingContent('');
      setInlines([]);
      setTools({});
      setToolsResults({});
      setLastProposalRound(null);
      const stream = await api.sendMessage(currentChatId, content, streamEnabled, signal);
      if (!(stream instanceof ReadableStream)) {
        return { streamedText: '', sources: [] as Source[] };
      }
      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let acc = '';
      let progressDone: number[] = [];
      const sourcesAcc: Source[] = [];
      const sourcesSeen = new Set<string>();
      const addSources = (raw: unknown) => {
        if (!Array.isArray(raw)) return;
        for (const s of raw) {
          if (!s || typeof s !== 'object') continue;
          const src = s as Source;
          const key = `${src.path ?? ''}#${src.page ?? ''}`;
          if (sourcesSeen.has(key)) continue;
          sourcesSeen.add(key);
          sourcesAcc.push(src);
        }
      };
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6).trim();
          if (data === '[DONE]') continue;
          try {
            const parsed = JSON.parse(data) as Record<string, unknown>;
            const type = parsed.type as string | undefined;

            switch (type) {
              case 'token':
                if (typeof parsed.content === 'string') {
                  acc += parsed.content;
                  setStreamedText(acc);
                  setProcessingText(null);
                }
                break;
              case 'step_status':
                if (typeof parsed.text === 'string') setProcessingText(parsed.text);
                break;
              case 'error':
                if (typeof parsed.message === 'string') {
                  setProcessingText(null);
                  appendMessage({ role: 'system', content: `Ошибка: ${parsed.message}` });
                }
                break;
              case 'pipeline_selected':
                setInlines((prev) => [
                  ...prev.filter((it) => it.kind !== 'pipeline_badge'),
                  {
                    kind: 'pipeline_badge',
                    pipelineName: (parsed.pipeline_name as string) ?? (parsed.pipeline_id as string),
                    mode: parsed.mode as string | undefined,
                  },
                ]);
                break;
              case 'pipeline_confirm_required':
                setInlines((prev) => [
                  ...prev.filter((it) => it.kind !== 'confirm'),
                  {
                    kind: 'confirm',
                    confirmToken: parsed.confirm_token as string,
                    pipelineName: (parsed.pipeline_name as string) ?? '',
                    reasoning: parsed.reasoning as string | undefined,
                  },
                ]);
                break;
              case 'validation_required':
                setInlines((prev) => [
                  ...prev.filter((it) => it.kind !== 'validation'),
                  {
                    kind: 'validation',
                    resumeToken: parsed.resume_token as string,
                    stepName: (parsed.step_name as string) ?? '',
                    content: parsed.content as string | undefined,
                    options: (parsed.options as string[]) ?? undefined,
                  },
                ]);
                break;
              case 'pipeline_resumed':
                setInlines((prev) => [
                  ...prev,
                  {
                    kind: 'pipeline_status',
                    type: 'pipeline_resumed',
                    preview: parsed.user_feedback_preview as string | undefined,
                  },
                ]);
                break;
              case 'pipeline_cancelled':
                setInlines((prev) => [
                  ...prev,
                  {
                    kind: 'pipeline_status',
                    type: 'pipeline_cancelled',
                    stepName: parsed.step_name as string | undefined,
                  },
                ]);
                break;
              case 'full_document_selection_required':
                setProcessingText(null);
                setInlines((prev) => [
                  ...prev.filter((it) => it.kind !== 'fulldoc'),
                  {
                    kind: 'fulldoc',
                    chatId: currentChatId,
                    candidates: (parsed.candidates as FullDocCandidate[]) ?? [],
                  },
                ]);
                break;
              case 'tool_call': {
                const round = (parsed.round as number) ?? 0;
                const tool = parsed.tool as string | undefined;
                if (tool === 'propose_context_update') {
                  setLastProposalRound(round);
                  break;
                }
                const info: ToolCallInfo = {
                  round,
                  queries: (parsed.queries as string[]) ?? [],
                  reason: parsed.reason as string | undefined,
                };
                setTools((prev) => ({ ...prev, [round]: info }));
                setInlines((prev) => [
                  ...prev.filter((it) => !(it.kind === 'tool_call' && it.round === round)),
                  { kind: 'tool_call', round, info },
                ]);
                break;
              }
              case 'context_update_proposal': {
                const fieldChangesCount = (parsed.field_changes_count as number) ?? 0;
                const statePatchCount = (parsed.state_patch_count as number) ?? 0;
                const fileChangesCount = (parsed.file_changes_count as number) ?? 0;
                const round = (parsed.round as number) ?? lastProposalRound ?? 0;
                // Build a generic summary — never surface the host-side
                // `note` here (e.g. "proposal created with 0 field_change(s)…").
                const summary =
                  statePatchCount > 0
                    ? `Обновить ${statePatchCount} значений${fieldChangesCount > 0 ? ` и ${fieldChangesCount} полей` : ''}${fileChangesCount > 0 ? `, ${fileChangesCount} файлов` : ''}`
                    : fieldChangesCount > 0
                      ? `Добавить ${fieldChangesCount} новых полей`
                      : fileChangesCount > 0
                        ? `Изменить ${fileChangesCount} файлов`
                        : 'Обновить контекст кампании';
                setInlines((prev) => [
                  ...prev.filter((it) => !(it.kind === 'proposal' && it.round === round)),
                  { kind: 'proposal', round, summary, fieldChangesCount, statePatchCount, fileChangesCount },
                ]);
                void queryClient.invalidateQueries({ queryKey: ['update-mode', currentChatId] });
                setProcessingText(null);
                break;
              }
              case 'tool_result': {
                const round = (parsed.round as number) ?? 0;
                const result: ToolResultInfo = {
                  round,
                  hits_count: parsed.hits_count as number | undefined,
                  scope: parsed.scope as string | undefined,
                  note: parsed.note as string | undefined,
                };
                setToolsResults((prev) => ({ ...prev, [round]: result }));
                addSources(parsed.sources);
                break;
              }
              case 'progress': {
                const step = (parsed.step as number) ?? 0;
                const total = (parsed.total as number) ?? 0;
                const stepName = parsed.step_name as string | undefined;
                setInlines((prev) => [
                  ...prev.filter((it) => it.kind !== 'progress'),
                  { kind: 'progress', step, total, stepName, doneSteps: progressDone },
                ]);
                break;
              }
              case 'step_done': {
                const step = (parsed.step as number) ?? 0;
                if (!progressDone.includes(step)) progressDone.push(step);
                setInlines((prev) =>
                  prev.map((it) =>
                    it.kind === 'progress' ? { ...it, doneSteps: [...progressDone] } : it,
                  ),
                );
                break;
              }
              case 'sources':
                addSources(parsed.sources);
                break;
              case 'clarification':
                if (typeof parsed.question === 'string' || typeof parsed.content === 'string') {
                  appendMessage({
                    role: 'clarification',
                    content: (parsed.question as string) ?? (parsed.content as string),
                    clarification_id: parsed.clarification_id as string | undefined,
                  });
                }
                break;
              default:
                break;
            }
          } catch {
            /* ignore */
          }
        }
      }
      setProcessingText(null);
      return { streamedText: acc, sources: sourcesAcc };
    },
    onSuccess: (result) => {
      setStreaming(false);
      setStreamedText('');
      setProcessingText(null);
      // Убираем инфо-плашки "Поиск в базе знаний" после полного завершения стрима.
      // Proposal-карточки намеренно оставляем — это активная review-сессия.
      setInlines((prev) => prev.filter((it) => it.kind !== 'tool_call'));
      if (result && 'streamedText' in result && result.streamedText) {
        const sources = 'sources' in result ? result.sources : undefined;
        appendMessage({
          role: 'assistant',
          content: result.streamedText,
          ...(sources && sources.length > 0 ? { sources } : {}),
        });
      }
      // После завершения — обновим список чатов (мог появиться новый)
      void queryClient.invalidateQueries({ queryKey: ['chats'] });
    },
    onError: (err) => {
      setStreaming(false);
      setStreamedText('');
      setProcessingText(null);
      setInlines([]);
      const msg = err instanceof Error ? err.message : 'Unknown error';
      if (msg.includes('LLM service unavailable') || msg.includes('generation model')) {
        appendMessage({
          role: 'system',
          content: 'Генеративная модель не настроена или недоступна. Перейдите в Настройки → Генеративные модели.',
        });
      } else {
        appendMessage({ role: 'system', content: `Ошибка: ${msg}` });
      }
    },
  });

  const cancelProposalMutation = useMutation({
    mutationFn: async (round: number) => {
      if (!currentChatId) throw new Error('No chat selected');
      await api.updateModeCancel(currentChatId);
      return round;
    },
    onSuccess: (round) => {
      setInlines((prev) => prev.filter((it) => !(it.kind === 'proposal' && it.round === round)));
      setShowUpdateModePanel(false);
      void queryClient.invalidateQueries({ queryKey: ['update-mode', currentChatId] });
    },
  });

  const handleSend = useCallback(
    (overrideContent?: string) => {
      const content = (overrideContent ?? input).trim();
      if (!content || !currentChatId || isStreaming) return;
      if (!overrideContent) setInput('');
      userScrolledUpRef.current = false;
      appendMessage({ role: 'user', content });
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      sendMutation.mutate({ content, signal: ctrl.signal });
    },
    [input, currentChatId, isStreaming, appendMessage, sendMutation],
  );

  // Глобальный слушатель «retry» от MessageBubble (для LLM unavailable)
  useEffect(() => {
    const onRetry = () => {
      if (isStreaming) return;
      const lastUser = [...messages].reverse().find((m) => m.role === 'user');
      if (lastUser) handleSend(lastUser.content);
    };
    window.addEventListener('mercer:retry-last', onRetry);
    return () => window.removeEventListener('mercer:retry-last', onRetry);
  }, [messages, isStreaming, handleSend]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const noChat = !currentChatId;

  // Сброс inline-карточек при смене чата
  useEffect(() => {
    setInlines([]);
    setTools({});
    setToolsResults({});
    setStreamedText('');
    setProcessingText(null);
  }, [currentChatId, setProcessingText]);

  // Колбэки для карточек
  const onConfirmPipeline = useCallback(
    async (token: string) => {
      if (!currentChatId) return;
      const res = await api.pipelineConfirm(currentChatId, token, 'confirm');
      const result = await handleNestedStream(res);
      removeInline((it) => it.kind === 'confirm' && it.confirmToken === token);
      if (result?.streamedText) {
        appendMessage({
          role: 'assistant',
          content: result.streamedText,
          ...(result.sources.length > 0 ? { sources: result.sources } : {}),
        });
      }
    },
    [currentChatId, handleNestedStream, appendMessage],
  );

  const onCancelPipelineConfirm = useCallback(
    async (token: string) => {
      if (!currentChatId) return;
      try {
        await api.pipelineConfirm(currentChatId, token, 'cancel');
      } catch {
        /* ignore */
      }
      removeInline((it) => it.kind === 'confirm' && it.confirmToken === token);
    },
    [currentChatId],
  );

  const onResumeValidation = useCallback(
    async (token: string, feedback: string | null) => {
      if (!currentChatId) return;
      const res = await api.pipelineResume(currentChatId, token, 'resume', feedback);
      const result = await handleNestedStream(res);
      removeInline((it) => it.kind === 'validation' && it.resumeToken === token);
      if (result?.streamedText) {
        appendMessage({
          role: 'assistant',
          content: result.streamedText,
          ...(result.sources.length > 0 ? { sources: result.sources } : {}),
        });
      }
    },
    [currentChatId, handleNestedStream, appendMessage],
  );

  const onCancelValidation = useCallback(
    async (token: string) => {
      if (!currentChatId) return;
      try {
        await api.pipelineResume(currentChatId, token, 'cancel', null);
      } catch {
        /* ignore */
      }
      removeInline((it) => it.kind === 'validation' && it.resumeToken === token);
    },
    [currentChatId],
  );

  const onConfirmFullDoc = useCallback(
    async (selectedIds: string[]) => {
      if (!currentChatId) return;
      const res = await api.fullDocConfirm(currentChatId, selectedIds);
      const result = await handleNestedStream(res);
      removeInline((it) => it.kind === 'fulldoc');
      if (result?.streamedText) {
        appendMessage({
          role: 'assistant',
          content: result.streamedText,
          ...(result.sources.length > 0 ? { sources: result.sources } : {}),
        });
      }
    },
    [currentChatId, handleNestedStream, appendMessage],
  );

  const onSkipFullDoc = useCallback(async () => {
    if (!currentChatId) return;
    const res = await api.fullDocConfirm(currentChatId, []);
    const result = await handleNestedStream(res);
    removeInline((it) => it.kind === 'fulldoc');
    if (result?.streamedText) {
      appendMessage({
        role: 'assistant',
        content: result.streamedText,
        ...(result.sources.length > 0 ? { sources: result.sources } : {}),
      });
    }
  }, [currentChatId, handleNestedStream, appendMessage]);

  return (
    <main className="flex flex-1 flex-col">
      <header className="relative flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-semibold text-text">
            {currentChat?.title ?? 'Выберите чат или создайте новый'}
          </h3>
          {currentDomainId && (
            <p className="truncate text-xs text-text-muted">
              Домен: <span className="font-mono">{currentDomainId}</span>
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <ModelHealthIndicator kind="generation" />
          <ModelHealthIndicator kind="embedding" />
          <ModelHealthIndicator kind="rerank" />
          <ModelHealthIndicator kind="drift" />
          <ModelHealthIndicator kind="sidecar" />
        </div>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={theme === 'light' ? 'Включить тёмную тему' : 'Включить светлую тему'}
          title={theme === 'light' ? 'Тёмная тема' : 'Светлая тема'}
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded text-text hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {theme === 'light' ? (
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          ) : (
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
            </svg>
          )}
        </button>
      </header>

      <ChatContextBar />

      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto px-4 py-4">
        {noChat ? (
          <div className="flex h-full items-center justify-center text-text-muted">
            <div className="text-center">
              <svg
                className="mx-auto mb-3 h-12 w-12 text-text-muted/50"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
              <p className="text-sm">Создайте беседу, чтобы начать</p>
            </div>
          </div>
        ) : (
          <div className="mx-auto w-full max-w-[90rem] space-y-4">
            {messages.map((m, i) => (
              <MessageBubble key={i} message={m} />
            ))}
            {isStreaming && streamedText && (
              <MessageBubble
                message={{ role: 'assistant', content: streamedText }}
                streaming
              />
            )}
            {inlines.map((item, idx) => {
              switch (item.kind) {
                case 'pipeline_badge':
                  return (
                    <div key={`pb-${idx}`}>
                      <PipelineBadge pipelineName={item.pipelineName} mode={item.mode} />
                    </div>
                  );
                case 'progress':
                  return (
                    <div key={`pg-${idx}`}>
                      <PipelineProgress
                        step={item.step}
                        total={item.total}
                        stepName={item.stepName}
                        doneSteps={item.doneSteps}
                      />
                    </div>
                  );
                case 'confirm':
                  return (
                    <div key={`pc-${item.confirmToken}`}>
                      <PipelineConfirmCard
                        pipelineName={item.pipelineName}
                        reasoning={item.reasoning}
                        onConfirm={() => onConfirmPipeline(item.confirmToken)}
                        onCancel={() => onCancelPipelineConfirm(item.confirmToken)}
                      />
                    </div>
                  );
                case 'validation':
                  return (
                    <div key={`vc-${item.resumeToken}`}>
                      <ValidationCard
                        stepName={item.stepName}
                        content={item.content}
                        options={item.options}
                        onResume={(fb) => onResumeValidation(item.resumeToken, fb)}
                        onCancel={() => onCancelValidation(item.resumeToken)}
                      />
                    </div>
                  );
                case 'fulldoc':
                  return (
                    <div key={`fd-${idx}`}>
                      <FullDocPanel
                        candidates={item.candidates}
                        onConfirm={onConfirmFullDoc}
                        onSkip={onSkipFullDoc}
                      />
                    </div>
                  );
                case 'tool_call':
                  return (
                    <div key={`tc-${item.round}`}>
                      <ToolCallCard
                        initialCall={item.info}
                        result={toolsResults[item.round] ?? null}
                      />
                    </div>
                  );
                case 'proposal':
                  return (
                    <ProposalCard
                      key={`pr-${item.round}`}
                      summary={item.summary}
                      fieldChangesCount={item.fieldChangesCount}
                      statePatchCount={item.statePatchCount}
                      fileChangesCount={item.fileChangesCount}
                      cancelling={cancelProposalMutation.isPending && cancelProposalMutation.variables === item.round}
                      onView={() => {
                        setShowUpdateModePanel(true);
                        requestAnimationFrame(() => {
                          const el = document.querySelector('[data-update-mode-panel]');
                          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        });
                      }}
                      onCancel={() => cancelProposalMutation.mutate(item.round)}
                    />
                  );
                case 'pipeline_status':
                  return (
                    <div key={`ps-${idx}`}>
                      <PipelineStatusLine
                        type={item.type}
                        userFeedbackPreview={item.preview}
                        stepName={item.stepName}
                      />
                    </div>
                  );
                default:
                  return null;
              }
            })}
            {currentChat?.campaign_id && currentChatId && showUpdateModePanel && (
              <div data-update-mode-panel>
                <UpdateModePanel
                  chatId={currentChatId}
                  onClose={() => setShowUpdateModePanel(false)}
                />
              </div>
            )}
            {currentChat?.campaign_id && currentChatId && draft && showContextDraftCard && (
              <div data-context-draft-card>
                <ContextDraftCard
                  chatId={currentChatId}
                  draft={draft}
                  onClose={() => setShowContextDraftCard(false)}
                />
              </div>
            )}
            {processingText && (
              <ProcessingStatus text={processingText} />
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {currentChatId && (
        <footer className="border-t border-border bg-surface p-3">
          <div className="mx-auto flex w-full max-w-[90rem] items-end gap-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Введите сообщение…"
              rows={1}
              disabled={isStreaming}
              className="flex-1 resize-none rounded border border-border bg-surface px-3 py-2 text-sm shadow-sm transition focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50"
            />
            {isStreaming ? (
              <Button variant="danger" onClick={handleStop}>
                Стоп
              </Button>
            ) : (
              <Button onClick={() => handleSend()} disabled={!input.trim()}>
                Отправить
              </Button>
            )}
          </div>
        </footer>
      )}

      {currentChat?.campaign_id && currentChatId && (
        <DriftStatusPopup chatId={currentChatId} />
      )}
    </main>
  );
}

function ProcessingStatus({ text }: { text: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="mx-auto flex w-fit items-center gap-2 rounded-full bg-surface-2 px-3 py-1.5 text-xs text-text-muted shadow-sm"
    >
      <span className="flex gap-0.5" aria-hidden="true">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:300ms]" />
      </span>
      <span>{text}</span>
    </div>
  );
}

function MessageBubble({ message, streaming }: { message: ChatMessage; streaming?: boolean }) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  if (isSystem) {
    return (
      <Card className="border-warning bg-warning/5">
        <p className="text-sm text-warning">{message.content}</p>
      </Card>
    );
  }

  const isLlmUnavailable = isLlmError(message.content);

  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      <div
        className={`max-w-[85%] rounded-lg px-4 py-2.5 ${
          isUser
            ? 'bg-primary text-white'
            : 'bg-surface-2 text-text'
        }`}
      >
        <Markdown
          content={message.content}
          variant={isUser ? 'inverse' : 'default'}
          className={streaming ? 'streaming' : ''}
        />
        {message.sources && message.sources.length > 0 && (
          <SourcesBlock sources={message.sources} text={message.content} />
        )}
        {isLlmUnavailable && !streaming && (
          <RetryButton
            onClick={() => {
              window.dispatchEvent(new CustomEvent('mercer:retry-last'));
            }}
          />
        )}
      </div>
    </div>
  );
}

function isLlmError(text: string): boolean {
  if (!text) return false;
  return (
    text.includes('LLM service unavailable') ||
    /llm.*(unavailable|error|timeout|refused)/i.test(text) ||
    /model.*not.*found/i.test(text) ||
    /generation model.*not configured/i.test(text)
  );
}

function RetryButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-2 inline-flex items-center gap-1 rounded border border-danger/30 bg-danger/10 px-2 py-1 text-xs font-medium text-danger hover:bg-danger/20"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="23 4 23 10 17 10" />
        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
      </svg>
      Повторить запрос
    </button>
  );
}

function SourcesBlock({ sources, text }: { sources: Source[]; text: string }) {
  const cited = new Set<number>();
  const re = /\[(\d+)\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    cited.add(parseInt(m[1]!, 10));
  }
  const visible = cited.size > 0
    ? sources.filter((_, i) => cited.has(i + 1))
    : sources;
  if (visible.length === 0) return null;

  return (
    <div className="mt-2 border-t border-border/40 pt-2 text-xs">
      <div className="font-semibold">Источники</div>
      <div className="mt-1 space-y-1">
        {visible.map((src, i) => (
          <div key={i} className="truncate text-text-muted">
            [{i + 1}] {src.path}
            {src.page != null && `, стр. ${src.page}`}
          </div>
        ))}
      </div>
    </div>
  );
}