import { Button } from '@/components/ui';
import type { WizardError } from './constants';

export interface WizardErrorBannerProps {
  error: WizardError | null;
  onDismiss?: () => void;
  onRetry?: () => void;
}

export function WizardErrorBanner({ error, onDismiss, onRetry }: WizardErrorBannerProps) {
  if (!error) return null;
  return (
    <div
      className="flex items-start justify-between gap-3 rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"
      role="alert"
      data-wizard-error
    >
      <div className="flex flex-col gap-1">
        <span>{error.text}</span>
        {error.code && (
          <span className="font-mono text-xs opacity-75">code: {error.code}</span>
        )}
      </div>
      <div className="flex shrink-0 gap-1">
        {onRetry && (
          <Button
            size="sm"
            variant="ghost"
            onClick={onRetry}
            data-wizard-error-retry
          >
            Повторить
          </Button>
        )}
        {onDismiss && (
          <button
            type="button"
            className="rounded p-1 text-danger hover:bg-danger/20"
            onClick={onDismiss}
            aria-label="Закрыть ошибку"
            data-wizard-error-dismiss
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}
