import { clsx } from '@/components/ui';
import type { Domain, DomainId } from '@/api/types';

interface DomainSelectorStripProps {
  domains: Domain[];
  currentDomainId: DomainId | null;
  loading?: boolean;
  onSelect: (domainId: DomainId) => void;
}

/**
 * Вычисляет количество колонок для сетки по числу доменов.
 * - 1..3 → 1..3 колонки (по числу доменов)
 * - 4..6 → ceil(N/2) колонок (2 строки)
 * - 7+    → ceil(N/3) колонок (3+ строки)
 */
function getCols(count: number): number {
  if (count <= 3) return count;
  if (count <= 6) return Math.ceil(count / 2);
  return Math.ceil(count / 3);
}

/**
 * Адаптивный размер/паддинг ячейки в зависимости от числа колонок и длины подписи.
 * Короткие имена (≤ 8 символов) при 3 колонках — 11px.
 * Длинные имена (> 8) при 3 колонках — 10px (помещаются без truncate).
 */
function pickSizeClass(cols: number, label: string): string {
  if (cols === 1) return 'text-sm py-2 px-3';
  if (cols === 2) return 'text-xs py-1 px-2';
  // cols >= 3
  return label.length > 8
    ? 'text-[10px] py-1 px-1'
    : 'text-[11px] py-1 px-1.5';
}

export function DomainSelectorStrip({
  domains,
  currentDomainId,
  loading = false,
  onSelect,
}: DomainSelectorStripProps) {
  if (loading) {
    return (
      <div
        className="grid gap-1.5"
        role="presentation"
        style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}
      >
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-7 animate-pulse rounded-md border border-border bg-surface-2"
          />
        ))}
      </div>
    );
  }

  if (domains.length === 0) {
    return <p className="text-xs text-text-muted">Нет доменов</p>;
  }

  const cols = getCols(domains.length);

  return (
    <div
      role="radiogroup"
      aria-label="Выбор домена"
      className="grid gap-1.5"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {domains.map((d) => {
        const isActive = d.domain_id === currentDomainId;
        const label = d.display_name ?? formatDomainName(d.domain_id);
        const sizeClass = pickSizeClass(cols, label);
        return (
          <button
            key={d.domain_id}
            type="button"
            role="radio"
            aria-checked={isActive}
            onClick={() => onSelect(d.domain_id)}
            title={label}
            data-testid={`domain-item-${d.domain_id}`}
            className={clsx(
              'flex items-center justify-center rounded-md border font-medium transition truncate',
              sizeClass,
              isActive
                ? 'border-primary bg-primary/15 text-primary'
                : 'border-border bg-surface text-text-muted hover:bg-surface-2 hover:text-text',
            )}
          >
            <span className="truncate">{label}</span>
          </button>
        );
      })}
    </div>
  );
}

const SPECIAL_NAMES: Record<string, string> = {
  dnd: 'D&D',
  work: 'Работа',
};

function formatDomainName(id: string): string {
  return SPECIAL_NAMES[id] ?? id.toUpperCase();
}
