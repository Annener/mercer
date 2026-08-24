import { Badge } from './Badge';

export type StatusKind = 'active' | 'inactive' | 'ready' | 'disabled';

const STATUS_LABELS: Record<StatusKind, string> = {
  active: 'Active',
  inactive: 'Inactive',
  ready: 'Ready',
  disabled: 'Disabled',
};

const STATUS_VARIANTS: Record<StatusKind, 'success' | 'default' | 'info'> = {
  active: 'success',
  ready: 'info',
  inactive: 'default',
  disabled: 'default',
};

interface StatusBadgeProps {
  kind: StatusKind;
}

export function StatusBadge({ kind }: StatusBadgeProps) {
  return (
    <Badge variant={STATUS_VARIANTS[kind]}>{STATUS_LABELS[kind]}</Badge>
  );
}
