import { useState } from 'react';
import { Button } from '@/components/ui';
import { Markdown } from '@/components/chat/Markdown';

interface PipelineConfirmCardProps {
  pipelineName: string;
  reasoning?: string;
  onConfirm: () => Promise<void> | void;
  onCancel: () => Promise<void> | void;
}

export function PipelineConfirmCard({
  pipelineName,
  reasoning,
  onConfirm,
  onCancel,
}: PipelineConfirmCardProps) {
  const [state, setState] = useState<'idle' | 'running' | 'ok' | 'cancelled' | 'error'>('idle');
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const handleConfirm = async () => {
    setState('running');
    try {
      await onConfirm();
      setState('ok');
    } catch (e) {
      setState('error');
      setErrMsg(e instanceof Error ? e.message : 'Ошибка');
    }
  };

  const handleCancel = async () => {
    setState('cancelled');
    try {
      await onCancel();
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-text">Запустить пайплайн</p>
          <p className="truncate text-xs text-text-muted">{pipelineName}</p>
        </div>
      </div>
      {reasoning && (
        <p className="mt-2 text-xs text-text-muted">{reasoning}</p>
      )}
      {state === 'idle' && (
        <div className="mt-3 flex gap-2">
          <Button size="sm" onClick={handleConfirm}>Запустить</Button>
          <Button size="sm" variant="ghost" onClick={handleCancel}>Отмена</Button>
        </div>
      )}
      {state === 'running' && (
        <div className="mt-3 flex items-center gap-2 text-xs text-info">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-info" aria-hidden="true" />
          Запускается…
        </div>
      )}
      {state === 'ok' && (
        <p className="mt-3 text-xs font-medium text-success">Запущен</p>
      )}
      {state === 'cancelled' && (
        <p className="mt-3 text-xs font-medium text-text-muted">Отменён</p>
      )}
      {state === 'error' && (
        <p className="mt-3 text-xs font-medium text-danger">Ошибка: {errMsg}</p>
      )}
    </div>
  );
}

interface ValidationCardProps {
  stepName: string;
  content?: string;
  options?: string[];
  onResume: (feedback: string | null) => Promise<void> | void;
  onCancel: () => Promise<void> | void;
}

export function ValidationCard({ stepName, content, options, onResume, onCancel }: ValidationCardProps) {
  const [state, setState] = useState<'idle' | 'ok' | 'cancelled' | 'error'>('idle');
  const [selected, setSelected] = useState<string | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const handleResume = async (feedback: string | null) => {
    setState('ok');
    try {
      await onResume(feedback);
    } catch (e) {
      setState('error');
      setErrMsg(e instanceof Error ? e.message : 'Ошибка');
    }
  };

  const handleCancel = async () => {
    setState('cancelled');
    try {
      await onCancel();
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="rounded-lg border border-warning/40 bg-warning/5 p-3">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-warning/10 text-warning" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-text">Требуется подтверждение</p>
          <p className="truncate text-xs text-text-muted">{stepName}</p>
        </div>
      </div>
      {content && (
        <div className="mt-2 rounded border border-border bg-surface p-2 text-xs">
          <Markdown content={content} />
        </div>
      )}
      {state === 'idle' && (
        <>
          {options && options.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {options.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  disabled={false}
                  className={`rounded border px-2 py-1 text-xs transition ${
                    selected === opt
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border bg-surface text-text hover:bg-surface-2'
                  }`}
                  onClick={() => {
                    setSelected(opt);
                    void handleResume(opt);
                  }}
                >
                  {opt}
                </button>
              ))}
              <Button size="sm" variant="ghost" onClick={handleCancel}>Отменить пайплайн</Button>
            </div>
          ) : (
            <div className="mt-3 flex gap-2">
              <Button size="sm" onClick={() => void handleResume(null)}>Продолжить</Button>
              <Button size="sm" variant="ghost" onClick={handleCancel}>Отменить пайплайн</Button>
            </div>
          )}
        </>
      )}
      {state === 'ok' && (
        <p className="mt-3 text-xs font-medium text-success">
          ✓ {selected ? selected.slice(0, 40) : 'Продолжить'}
        </p>
      )}
      {state === 'cancelled' && (
        <p className="mt-3 text-xs font-medium text-text-muted">Пайплайн отменён</p>
      )}
      {state === 'error' && (
        <p className="mt-3 text-xs font-medium text-danger">Ошибка: {errMsg}</p>
      )}
    </div>
  );
}
