import type { ReactNode } from 'react';
import { clsx } from './clsx';

interface CardProps {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Card({ title, actions, children, className }: CardProps) {
  return (
    <section className={clsx('rounded-lg border border-border bg-surface shadow-sm', className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between border-b border-border px-4 py-2.5">
          {title && <h3 className="text-sm font-semibold text-text">{title}</h3>}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

interface EmptyStateProps {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function EmptyState({ title, description, actions, className }: EmptyStateProps) {
  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-surface px-6 py-10 text-center',
        className,
      )}
    >
      {title && <h4 className="text-sm font-medium text-text">{title}</h4>}
      {description && <p className="text-xs text-text-muted">{description}</p>}
      {actions && <div className="mt-2 flex gap-2">{actions}</div>}
    </div>
  );
}