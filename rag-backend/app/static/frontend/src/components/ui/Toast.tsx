import { useToasts, type ToastVariant } from './toastStore';

const VARIANT_STYLES: Record<ToastVariant, string> = {
  default: 'bg-surface-2 text-text border-border',
  success: 'bg-success/10 text-success border-success/30',
  danger: 'bg-danger/10 text-danger border-danger/30',
  warning: 'bg-warning/10 text-warning border-warning/30',
  info: 'bg-info/10 text-info border-info/30',
};

export function ToastViewport() {
  const { toasts, dismiss } = useToasts();
  if (toasts.length === 0) return null;
  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-4 z-[2000] flex flex-col items-center gap-2 px-4"
      role="status"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          data-testid="toast"
          data-toast-variant={t.variant}
          className={
            'pointer-events-auto flex max-w-md items-start gap-2 rounded border px-3 py-2 text-sm shadow ' +
            VARIANT_STYLES[t.variant]
          }
        >
          <span className="flex-1">{t.message}</span>
          <button
            type="button"
            onClick={() => dismiss(t.id)}
            className="rounded p-1 text-text-muted hover:bg-surface-2"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
