import { useEffect, useRef, useState } from 'react';
import { Button, clsx } from '@/components/ui';
import { api } from '@/api/client';
import type { DriftPhase, DriftStatus, UUID } from '@/api/types';

const AUTO_HIDE_MS = 5000;

interface Props {
  chatId: UUID;
}

export function DriftStatusPopup({ chatId }: Props) {
  const [status, setStatus] = useState<DriftStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const lastPhaseRef = useRef<DriftPhase | null>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Подключаемся к SSE + сразу подтягиваем текущий статус (catch-up).
  useEffect(() => {
    setDismissed(false);
    setStatus(null);
    lastPhaseRef.current = null;

    // Catch-up через poll-endpoint. Если SSE поднимется и продублирует —
    // новое событие перезапишет state (без скачков UI).
    void api.getDriftStatus(chatId).then(
      (s) => {
        // Не показываем окошко только потому что Redis ещё не пустой —
        // показываем только активные фазы или draft_ready.
        if (s.phase !== 'idle' || s.message) {
          setStatus(s);
        }
      },
      () => {
        /* ignore — SSE подхватит */
      },
    );

    const url = api.getChatEventsStreamUrl(chatId);
    const es = new EventSource(url);

    es.onmessage = (ev) => {
      if (ev.data === '[DONE]') return;
      try {
        const parsed = JSON.parse(ev.data) as Record<string, unknown>;
        if (parsed.type === 'error') return; // stream-level error: не путать с drift error
        const next = parsed as unknown as DriftStatus;
        setStatus(next);
        lastPhaseRef.current = next.phase;
        // Новый реальный сигнал — снова показываем.
        setDismissed(false);
      } catch {
        /* ignore non-JSON frames (heartbeat и пр.) */
      }
    };

    es.onerror = () => {
      // EventSource сам реконнектится; явного close не делаем, если только
      // не уверены, что вернулись ошибки CORS — тогда спасёт poll.
    };

    return () => {
      es.close();
    };
  }, [chatId]);

  // Авто-сворачивание по фазе.
  useEffect(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
    if (!status) return;
    if (status.phase === 'detecting' || status.phase === 'drafting') {
      setExpanded(false);
      return;
    }
    if (status.phase === 'draft_ready') {
      setExpanded(true);
      return;
    }
    if (status.phase === 'error') {
      setExpanded(true);
      // Не исчезаем автоматически — пусть пользователь увидит и закроет сам.
      return;
    }
    if (status.phase === 'idle') {
      // Если просто пустой idle без сообщения — вообще не показываем.
      if (!status.message) {
        setDismissed(true);
        return;
      }
      hideTimerRef.current = setTimeout(() => {
        setDismissed(true);
        hideTimerRef.current = null;
      }, AUTO_HIDE_MS);
    }
    return () => {
      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current);
        hideTimerRef.current = null;
      }
    };
  }, [status?.phase, status?.message, status?.published_at]);

  if (!status || dismissed) return null;

  const onJump = () => {
    requestAnimationFrame(() => {
      const el = document.querySelector('[data-context-draft-card]');
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    setDismissed(true);
  };

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-auto fixed right-4 top-4 z-40 w-80 rounded-2xl
                 border border-white/30 bg-white/60 px-3.5 py-3 shadow-xl
                 backdrop-blur-md transition
                 dark:border-white/10 dark:bg-black/40"
    >
      <Header
        phase={status.phase}
        message={status.message}
        error={status.error}
        onClose={() => setDismissed(true)}
      />
      <Body
        status={status}
        expanded={expanded}
        onExpandToggle={() => setExpanded((v) => !v)}
        onOpenDraft={onJump}
      />
    </div>
  );
}

interface HeaderProps {
  phase: DriftPhase;
  message: string | null;
  error: string | null;
  onClose: () => void;
}

function Header({ phase, message, error, onClose }: HeaderProps) {
  const title =
    phase === 'detecting'
      ? 'Drift loop: анализ'
      : phase === 'drafting'
        ? 'Drift loop: формирование'
        : phase === 'draft_ready'
          ? 'Готово'
          : phase === 'error'
            ? 'Drift loop: ошибка'
            : 'Drift loop';

  const indicator = (
    <span
      aria-hidden="true"
      className={clsx(
        'inline-block h-2 w-2 shrink-0 rounded-full',
        phase === 'error' && 'bg-red-500',
        phase === 'draft_ready' && 'bg-success',
        (phase === 'detecting' || phase === 'drafting') && 'bg-primary animate-pulse',
        phase === 'idle' && 'bg-text-muted',
      )}
    />
  );

  return (
    <div className="flex items-start gap-2">
      {indicator}
      <div className="min-w-0 flex-1">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
          {title}
        </div>
        <div
          className={clsx(
            'mt-0.5 text-sm leading-snug',
            phase === 'error' ? 'text-red-700 dark:text-red-300' : 'text-text',
          )}
        >
          {error ?? message ?? 'В фоне ничего не происходит.'}
        </div>
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="Скрыть"
        title="Скрыть"
        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-text-muted transition hover:bg-white/40 hover:text-text focus:outline-none focus-visible:ring-2 focus-visible:ring-primary dark:hover:bg-black/40"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <line x1="6" y1="6" x2="18" y2="18" />
          <line x1="6" y1="18" x2="18" y2="6" />
        </svg>
      </button>
    </div>
  );
}

interface BodyProps {
  status: DriftStatus;
  expanded: boolean;
  onExpandToggle: () => void;
  onOpenDraft: () => void;
}

function Body({ status, expanded, onExpandToggle, onOpenDraft }: BodyProps) {
  if (status.phase === 'draft_ready') {
    const ops = status.draft_ops_count ?? 0;
    return (
      <div className="mt-2.5 space-y-2">
        <div className="flex flex-wrap items-baseline gap-2 text-xs text-text-muted">
          <span className="font-medium text-text">Найдено {ops} предложений</span>
          {typeof status.drift_hints_count === 'number' &&
            status.drift_hints_count > 0 && (
              <span>из {status.drift_hints_count} подсказок</span>
            )}
        </div>
        {status.draft_summary && (
          <div className="rounded-md bg-white/40 px-2 py-1.5 text-xs text-text dark:bg-black/30">
            {status.draft_summary}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-0.5">
          <Button size="sm" variant="ghost" onClick={onExpandToggle}>
            {expanded ? 'Скрыть детали' : 'Подробнее'}
          </Button>
          <Button size="sm" onClick={onOpenDraft}>
            Открыть
          </Button>
        </div>
        {expanded && (
          <div className="rounded-md border border-border/40 bg-white/40 px-2 py-1.5 text-[11px] text-text-muted dark:bg-black/30">
            Карточка «Возможные обновления» уже в чате ниже — нажмите «Открыть», чтобы перейти к ней.
          </div>
        )}
      </div>
    );
  }

  if (status.phase === 'error') {
    return (
      <div className="mt-2 flex justify-end">
        <Button size="sm" variant="ghost" onClick={onOpenDraft}>
          Перейти к чату
        </Button>
      </div>
    );
  }

  if (status.phase === 'detecting' || status.phase === 'drafting') {
    return (
      <div className="mt-2.5 flex items-center gap-1.5 text-text-muted" aria-hidden="true">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:300ms]" />
        <span className="ml-1 text-[11px]">локальная модель работает</span>
      </div>
    );
  }

  // idle / fallback
  return null;
}
