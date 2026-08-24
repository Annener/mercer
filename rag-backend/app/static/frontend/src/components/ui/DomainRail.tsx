import { clsx } from './clsx';
import type { Domain, DomainId } from '@/api/types';

interface DomainRailProps {
  domains: Domain[];
  selectedDomainId: DomainId | null;
  onSelect: (domainId: DomainId | null) => void;
  hideAll?: boolean;
}

interface AvatarColor {
  bg: string;
  fg: string;
}

const AVATAR_COLORS: ReadonlyArray<AvatarColor> = [
  { bg: '#3498db', fg: '#fff' },
  { bg: '#27ae60', fg: '#fff' },
  { bg: '#8e44ad', fg: '#fff' },
  { bg: '#e67e22', fg: '#fff' },
  { bg: '#16a085', fg: '#fff' },
  { bg: '#c0392b', fg: '#fff' },
  { bg: '#2980b9', fg: '#fff' },
  { bg: '#d35400', fg: '#fff' },
];

function getInitial(domain: Domain): string {
  const name = domain.display_name || domain.domain_id || '?';
  return name.charAt(0).toUpperCase();
}

function getAvatarColor(index: number): AvatarColor {
  return AVATAR_COLORS[index % AVATAR_COLORS.length] as AvatarColor;
}

export function DomainRail({
  domains,
  selectedDomainId,
  onSelect,
  hideAll = false,
}: DomainRailProps) {
  const visible = domains.filter((d) => d.domain_id !== 'default');

  const isAllActive = selectedDomainId === null;

  return (
    <nav
      aria-label="Домены"
      className="flex w-full shrink-0 flex-col overflow-hidden rounded-none border border-border border-t-0 bg-surface-2 md:w-[180px] md:rounded-b-lg"
    >
      <span className="block px-4 pb-2 pt-2.5 text-center text-xs font-bold uppercase tracking-wider text-text-muted">
        Домены
      </span>

      <div className="flex flex-row overflow-x-auto md:flex-col">
        {!hideAll && (
          <button
            type="button"
            data-domain-id=""
            aria-pressed={isAllActive}
            onClick={() => onSelect(null)}
            className={clsx(
              'flex h-[120px] w-[120px] shrink-0 flex-col items-center justify-center gap-1.5 bg-surface px-2.5 py-3 text-center text-text transition-colors hover:bg-surface-2 hover:text-primary md:w-full md:border-b md:border-border',
              isAllActive && 'border-l-[3px] border-l-primary bg-info/10 pl-[7px] font-semibold text-primary',
            )}
          >
            <span
              className={clsx(
                'flex h-10 w-10 items-center justify-center rounded-full bg-bg text-lg font-bold uppercase text-text-muted',
                isAllActive && 'bg-primary text-white',
              )}
              aria-hidden="true"
            >
              ☰
            </span>
            <span className="w-full truncate text-xs leading-tight">Все домены</span>
          </button>
        )}

        {visible.map((d, idx) => {
          const isActive = d.domain_id === selectedDomainId;
          const initial = getInitial(d);
          const color = getAvatarColor(idx);
          return (
            <button
              key={d.domain_id}
              type="button"
              data-domain-id={d.domain_id}
              aria-pressed={isActive}
              onClick={() => onSelect(d.domain_id)}
              className={clsx(
                'flex h-[120px] w-[120px] shrink-0 flex-col items-center justify-center gap-1.5 bg-surface px-2.5 py-3 text-center text-text transition-colors hover:bg-surface-2 hover:text-primary md:w-full md:border-b md:border-border',
                isActive && 'border-l-[3px] border-l-primary bg-info/10 pl-[7px] font-semibold text-primary',
              )}
            >
              <span
                className={clsx(
                  'flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-base font-bold uppercase text-text-muted',
                  isActive && 'bg-primary text-white',
                )}
                style={
                  isActive
                    ? undefined
                    : { background: color.bg, color: color.fg }
                }
                aria-hidden="true"
              >
                {initial}
              </span>
              <span className="w-full truncate text-xs leading-tight">
                {d.display_name || d.domain_id}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}