import { clsx } from '@/components/ui';

export type WizardStep = 1 | 2 | 3;

export interface WizardStepperProps {
  currentStep: WizardStep;
  className?: string;
}

const STEPS: ReadonlyArray<{ step: WizardStep; label: string }> = [
  { step: 1, label: 'Документы' },
  { step: 2, label: 'Сводка' },
  { step: 3, label: 'Результат' },
];

export function WizardStepper({ currentStep, className }: WizardStepperProps) {
  return (
    <div
      className={clsx(
        'flex items-center gap-2 border-b border-border pb-3',
        className,
      )}
      role="progressbar"
      aria-valuemin={1}
      aria-valuemax={3}
      aria-valuenow={currentStep}
    >
      {STEPS.map((s, i) => {
        const isActive = s.step === currentStep;
        const isDone = s.step < currentStep;
        return (
          <div key={s.step} className="flex items-center gap-2">
            <span
              className={clsx(
                'flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold transition-colors',
                isActive && 'bg-primary text-bg',
                isDone && 'bg-success text-bg',
                !isActive && !isDone && 'bg-surface-2 text-text-muted',
              )}
              aria-hidden="true"
            >
              {isDone ? '✓' : s.step}
            </span>
            <span
              className={clsx(
                'text-sm',
                isActive ? 'font-semibold' : 'text-text-muted',
              )}
            >
              {s.label}
            </span>
            {i < STEPS.length - 1 && (
              <span
                className={clsx(
                  'mx-1 h-px w-8',
                  isDone ? 'bg-success' : 'bg-border',
                )}
                aria-hidden="true"
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
