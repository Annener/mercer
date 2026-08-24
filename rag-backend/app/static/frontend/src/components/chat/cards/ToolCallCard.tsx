import { useEffect, useState } from 'react';

export interface ToolCallInfo {
  round: number;
  queries?: string[];
  reason?: string;
}

export interface ToolResultInfo {
  round: number;
  hits_count?: number;
  scope?: string;
  note?: string;
}

interface ToolCallCardProps {
  initialCall: ToolCallInfo;
  result?: ToolResultInfo | null;
}

export function ToolCallCard({ initialCall, result }: ToolCallCardProps) {
  const [info, setInfo] = useState<ToolResultInfo | null>(result ?? null);

  useEffect(() => {
    if (result) setInfo(result);
  }, [result]);

  const queries = (initialCall.queries ?? []).slice(0, 3).join(', ') || '(пустой запрос)';
  const hits = info?.hits_count ?? 0;
  const scope = info?.scope ?? 'domain';
  const note = info?.note ?? '';

  return (
    <div
      className="mx-auto w-fit rounded border border-accent/30 bg-accent/5 px-3 py-2 text-xs text-text-muted"
      data-round={initialCall.round}
    >
      <div className="flex items-center gap-1.5">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="text-accent">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <span className="font-medium text-text">Поиск в базе знаний</span>
      </div>
      <div className="mt-1 truncate font-mono text-[11px]" title={queries}>
        {queries}
      </div>
      {initialCall.reason && (
        <div className="mt-0.5 italic text-[11px]">{initialCall.reason}</div>
      )}
      {info ? (
        <div className="mt-1 text-[11px]">
          Найдено фрагментов: <strong>{hits}</strong>{' '}
          <span className="text-text-muted">({scope})</span>
          {note && <span className="italic"> — {note}</span>}
        </div>
      ) : (
        <div className="mt-1 flex items-center gap-1 text-[11px]">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
          ищу…
        </div>
      )}
    </div>
  );
}
