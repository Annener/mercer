import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { clsx } from './clsx';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
  children: ReactNode;
  hideCloseButton?: boolean;
}

const sizeStyles: Record<NonNullable<ModalProps['size']>, string> = {
  sm: 'max-w-md',
  md: 'max-w-2xl',
  lg: 'max-w-4xl',
};

export function Modal({ open, onClose, title, size = 'md', children, hideCloseButton }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={clsx(
          'flex max-h-[90vh] w-full flex-col overflow-hidden rounded-lg bg-surface shadow-lg',
          sizeStyles[size],
        )}
      >
        {(title || !hideCloseButton) && (
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h3 className="text-base font-semibold text-text">{title}</h3>
            {!hideCloseButton && (
              <button
                type="button"
                onClick={onClose}
                className="rounded p-1 text-text-muted hover:bg-surface-2 hover:text-text"
                aria-label="Закрыть"
              >
                ×
              </button>
            )}
          </div>
        )}
        <div className="flex-1 overflow-auto">{children}</div>
      </div>
    </div>
  );
}