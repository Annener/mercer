import { Button } from '@/components/ui';

export interface ProposalCardProps {
  summary: string;
  fieldChangesCount: number;
  statePatchCount: number;
  fileChangesCount: number;
  onView: () => void;
  onCancel: () => void;
  cancelling?: boolean;
}

export function ProposalCard({
  summary,
  fieldChangesCount,
  statePatchCount,
  fileChangesCount,
  onView,
  onCancel,
  cancelling,
}: ProposalCardProps) {
  const counters: string[] = [];
  if (fieldChangesCount > 0) counters.push(`поля: ${fieldChangesCount}`);
  if (statePatchCount > 0) counters.push(`значения: ${statePatchCount}`);
  if (fileChangesCount > 0) counters.push(`файлы: ${fileChangesCount}`);
  const countersText = counters.length > 0 ? counters.join(', ') : 'нет изменений';

  return (
    <div className="relative ml-2 mb-3 max-w-md self-start">
      <div className="relative rounded-2xl rounded-bl-sm border-2 border-primary/40 bg-primary/5 px-4 py-3 shadow-sm">
        <div className="absolute -left-[7px] top-5 h-3 w-3 rotate-45 border-b-2 border-l-2 border-primary/40 bg-primary/5" aria-hidden="true" />
        <div className="flex items-start gap-2">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="mt-0.5 shrink-0 text-primary">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
          </svg>
          <div className="min-w-0 flex-1">
            <div className="text-xs font-semibold text-primary">
              Предложение обновить контекст
            </div>
            <div className="mt-1 text-sm text-text">
              {summary}
            </div>
            <div className="mt-1 text-[11px] text-text-muted">
              {countersText}
            </div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelling}
            aria-label="Отменить предложение"
            title="Отменить предложение"
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-text-muted transition hover:bg-surface-2 hover:text-text focus:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="6" y1="6" x2="18" y2="18" />
              <line x1="6" y1="18" x2="18" y2="6" />
            </svg>
          </button>
        </div>
        <div className="mt-3 flex justify-end">
          <Button size="sm" onClick={onView}>
            Посмотреть
          </Button>
        </div>
      </div>
    </div>
  );
}