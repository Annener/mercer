import { useRef, useState, type ReactNode } from 'react';
import { useClickOutside } from '@/hooks/useClickOutside';
import { clsx } from './clsx';

export interface SettingsCardMenuItem {
  key: string;
  label: string;
  disabled?: boolean;
  danger?: boolean;
  onClick: () => void;
}

interface SettingsCardProps {
  title: string;
  subtitle?: string;
  badges?: ReactNode;
  meta?: ReactNode;
  menu?: SettingsCardMenuItem[];
  active?: boolean;
  footer?: ReactNode;
  className?: string;
}

export function SettingsCard({
  title,
  subtitle,
  badges,
  meta,
  menu,
  active = true,
  footer,
  className,
}: SettingsCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useClickOutside(menuRef, () => setMenuOpen(false), menuOpen);

  const hasMenu = !!menu && menu.length > 0;

  return (
    <div
      className={clsx(
        'relative flex min-h-[108px] flex-col rounded-xl bg-surface p-4 shadow-sm transition-opacity',
        active ? 'border-2 border-success' : 'border border-border opacity-90',
        className,
      )}
    >
      <div className="flex flex-1 flex-col gap-2">
        <div className="flex items-center gap-2">
          <h3 className="flex-1 min-w-0 truncate text-xl font-semibold leading-tight text-text">
            {title}
          </h3>
          {badges && <div className="flex shrink-0 items-center gap-1">{badges}</div>}
          {hasMenu && (
            <div ref={menuRef} className="relative shrink-0">
              <button
                type="button"
                aria-label="Действия"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((v) => !v)}
                className="flex min-h-[32px] min-w-[32px] items-center justify-center rounded p-1.5 text-2xl leading-none text-text-muted hover:bg-surface-2 hover:text-text"
              >
                ⋮
              </button>
              {menuOpen && (
                <div
                  role="menu"
                  className="absolute right-0 top-full z-20 mt-1 min-w-[160px] rounded-md border border-border bg-surface py-1 shadow-md"
                >
                  {menu!.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      role="menuitem"
                      disabled={item.disabled}
                      onClick={() => {
                        if (item.disabled) return;
                        setMenuOpen(false);
                        item.onClick();
                      }}
                      className={clsx(
                        'block w-full px-3 py-1.5 text-left text-sm hover:bg-surface-2',
                        item.disabled && 'cursor-not-allowed disabled:opacity-50',
                        item.danger ? 'text-danger' : 'text-text',
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {subtitle && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-text-muted">{subtitle}</span>
          </div>
        )}

        {meta && <div className="truncate text-sm text-text-muted">{meta}</div>}

        {footer && <div className="mt-auto pt-2">{footer}</div>}
      </div>
    </div>
  );
}