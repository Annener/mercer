import { Button } from '@/components/ui';
import type { CampaignStateVersion } from '@/api/types';

export interface ResultStepProps {
  version: CampaignStateVersion | null;
  onClose: () => void;
}

export function ResultStep({ version, onClose }: ResultStepProps) {
  const summary = version?.summary;
  const fields = version?.fields ?? [];

  return (
    <div
      className="flex flex-col items-center gap-3 py-4 text-center"
      data-result-step
    >
      <div className="rounded-full bg-success/20 px-3 py-1 text-sm font-semibold text-success">
        ✓ Initial State применён
      </div>

      <p className="text-xs text-text-muted">
        state_version = {summary?.state_version ?? '—'}
        {summary?.source_kind ? ` · source_kind = ${summary.source_kind}` : ''}
      </p>

      <div className="w-full max-w-md rounded border border-border bg-surface-2 p-3 text-left text-sm">
        {fields.length === 0 ? (
          <p className="text-text-muted">Нет записанных полей.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {fields.map((f) => (
              <li key={f.field_key} className="flex flex-col gap-0.5">
                <span className="font-mono text-xs text-text-muted">
                  {f.field_key}
                </span>
                {f.mode === 'single' && f.single_value && (
                  <span className="text-sm">{f.single_value.text}</span>
                )}
                {f.mode === 'list' && (
                  <span className="text-xs text-text-muted">
                    элементов: {f.items?.length ?? 0}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <Button onClick={onClose} data-result-close>
        Готово
      </Button>
    </div>
  );
}
