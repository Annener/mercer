import type { ReactNode } from 'react';
import { clsx } from './clsx';

interface TabItem {
  id: string;
  label: ReactNode;
  badge?: ReactNode;
  disabled?: boolean;
}

interface TabsProps {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}

export function Tabs({ items, value, onChange, className }: TabsProps) {
  return (
    <div
      role="tablist"
      className={clsx('flex flex-wrap gap-1 border-b border-border', className)}
    >
      {items.map((item) => {
        const active = item.id === value;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={item.disabled}
            onClick={() => onChange(item.id)}
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-t px-3 py-2 text-sm font-medium',
              'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary',
              active
                ? 'border-b-2 border-primary text-primary'
                : 'border-b-2 border-transparent text-text-muted hover:bg-surface-2 hover:text-text',
              item.disabled && 'cursor-not-allowed opacity-50',
            )}
          >
            {item.label}
            {item.badge}
          </button>
        );
      })}
    </div>
  );
}