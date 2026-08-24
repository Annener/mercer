import type { CSSProperties, ReactNode } from 'react';
import { clsx } from './clsx';

type Variant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'primary';

const variantStyles: Record<Variant, string> = {
  default: 'bg-surface-2 text-text-muted',
  primary: 'bg-primary/10 text-primary',
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  danger: 'bg-danger/10 text-danger',
  info: 'bg-info/10 text-info',
};

interface BadgeProps {
  variant?: Variant;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}

export function Badge({ variant = 'default', children, className, style }: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        variantStyles[variant],
        className,
      )}
      style={style}
    >
      {children}
    </span>
  );
}