interface PipelineProgressProps {
  step: number;
  total: number;
  stepName?: string;
  doneSteps?: number[];
}

export function PipelineProgress({ step, total, stepName, doneSteps = [] }: PipelineProgressProps) {
  const doneSet = new Set(doneSteps);
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
      {Array.from({ length: total }, (_, i) => {
        const n = i + 1;
        const isDone = doneSet.has(n) || n < step;
        const isActive = !isDone && n === step;
        return (
          <span
            key={n}
            className={`inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-semibold ${
              isDone
                ? 'border-success bg-success/10 text-success'
                : isActive
                  ? 'border-info bg-info/10 text-info'
                  : 'border-border bg-surface text-text-muted'
            }`}
            title={`Шаг ${n}${isDone ? ' (готов)' : isActive ? ' (текущий)' : ''}`}
          >
            {isDone ? '✓' : n}
          </span>
        );
      })}
      {stepName && <em className="ml-1 text-text-muted">{stepName}</em>}
    </div>
  );
}

interface PipelineBadgeProps {
  pipelineName?: string;
  mode?: string;
}

export function PipelineBadge({ pipelineName, mode }: PipelineBadgeProps) {
  return (
    <div className="mb-1 inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
      </svg>
      {pipelineName ?? 'pipeline'}{mode ? ` · ${mode}` : ''}
    </div>
  );
}

interface PipelineStatusLineProps {
  type: 'pipeline_resumed' | 'pipeline_cancelled';
  userFeedbackPreview?: string | null;
  stepName?: string;
}

export function PipelineStatusLine({ type, userFeedbackPreview, stepName }: PipelineStatusLineProps) {
  if (type === 'pipeline_resumed') {
    const preview = userFeedbackPreview ? ` — «${userFeedbackPreview}»` : '';
    return (
      <div className="mx-auto w-fit rounded bg-info/10 px-2 py-1 text-[11px] font-medium text-info">
        ▶ Пайплайн продолжен{preview}
      </div>
    );
  }
  return (
    <div className="mx-auto w-fit rounded bg-surface-2 px-2 py-1 text-[11px] font-medium text-text-muted">
      ✕ Пайплайн отменён{stepName ? ` на шаге «${stepName}»` : ''}
    </div>
  );
}
