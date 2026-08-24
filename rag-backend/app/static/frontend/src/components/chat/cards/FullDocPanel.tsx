import { useMemo, useState } from 'react';
import { Button } from '@/components/ui';

export interface FullDocCandidate {
  document_id: string;
  title?: string;
  source_path?: string;
  estimated_tokens?: number | null;
  already_sent?: boolean;
}

interface FullDocPanelProps {
  candidates: FullDocCandidate[];
  onConfirm: (selectedIds: string[]) => Promise<void> | void;
  onSkip: () => Promise<void> | void;
}

export function FullDocPanel({ candidates, onConfirm, onSkip }: FullDocPanelProps) {
  const [selected, setSelected] = useState<Set<string>>(() => {
    const s = new Set<string>();
    for (const c of candidates) if (c.already_sent) s.add(c.document_id);
    return s;
  });
  const [locked, setLocked] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const totalTokens = useMemo(() => {
    let total = 0;
    candidates.forEach((c) => {
      if (selected.has(c.document_id)) total += c.estimated_tokens ?? 0;
    });
    return total;
  }, [candidates, selected]);

  const toggle = (id: string) => {
    if (locked) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleConfirm = async () => {
    setLocked(true);
    try {
      await onConfirm(Array.from(selected));
    } catch (e) {
      setLocked(false);
      setErrMsg(e instanceof Error ? e.message : 'Ошибка');
    }
  };

  const handleSkip = async () => {
    setLocked(true);
    try {
      await onSkip();
    } catch (e) {
      setLocked(false);
      setErrMsg(e instanceof Error ? e.message : 'Ошибка');
    }
  };

  return (
    <div
      className={`rounded-lg border border-info/30 bg-info/5 p-3 transition ${
        locked ? 'opacity-60' : ''
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-info/10 text-info" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-text">Выберите документы для полной отправки</p>
          <p className="text-xs text-text-muted">
            Найдены релевантные документы. Отметьте те, которые нужно передать в модель целиком.
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-1.5">
        {candidates.map((c) => {
          const tokensText =
            c.estimated_tokens != null ? `~${c.estimated_tokens.toLocaleString('ru-RU')} токенов` : '';
          return (
            <label
              key={c.document_id}
              className="flex cursor-pointer items-center gap-2 rounded border border-border bg-surface px-2 py-1.5 text-xs hover:bg-surface-2"
            >
              <input
                type="checkbox"
                checked={selected.has(c.document_id)}
                onChange={() => toggle(c.document_id)}
                disabled={locked}
                className="h-3.5 w-3.5 cursor-pointer accent-primary"
              />
              <span className="min-w-0 flex-1 truncate" title={c.source_path ?? c.title ?? c.document_id}>
                {c.title ?? c.document_id}
              </span>
              {tokensText && <span className="text-text-muted">{tokensText}</span>}
              {c.already_sent && (
                <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-text-muted">
                  уже загружен
                </span>
              )}
            </label>
          );
        })}
      </div>

      <div className="mt-2 text-xs text-text-muted">
        Выбрано: <strong>{totalTokens.toLocaleString('ru-RU')}</strong> токенов
      </div>

      {errMsg && <p className="mt-2 text-xs text-danger">Ошибка: {errMsg}</p>}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={handleConfirm} disabled={locked}>
          Продолжить с выбранными
        </Button>
        <Button size="sm" variant="ghost" onClick={handleSkip} disabled={locked}>
          Без полных документов
        </Button>
      </div>
    </div>
  );
}
