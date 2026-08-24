import { useRef, useState, type CSSProperties } from 'react';
import { useClickOutside } from '@/hooks/useClickOutside';
import { Badge } from './Badge';
import { clsx } from './clsx';
import type { TagRead } from '@/api/types';

interface TagOverflowProps {
  tags: TagRead[];
  max?: number;
  emptyHint?: string;
  className?: string;
}

export function TagOverflow({ tags, max = 5, emptyHint = '—', className }: TagOverflowProps) {
  if (tags.length === 0) {
    return <span className={clsx('text-xs text-text-muted', className)}>{emptyHint}</span>;
  }
  const visible = tags.slice(0, max);
  const overflow = tags.slice(max);
  return (
    <div className={clsx('flex flex-wrap items-center gap-1', className)}>
      {visible.map((t) => (
        <TagBadge key={t.id} tag={t} />
      ))}
      {overflow.length > 0 && <TagOverflowPopover tags={overflow} count={overflow.length} />}
    </div>
  );
}

interface TagOverflowPopoverProps {
  tags: TagRead[];
  count: number;
}

function TagOverflowPopover({ tags, count }: TagOverflowPopoverProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  useClickOutside(containerRef, () => setOpen(false), open);

  return (
    <div ref={containerRef} className="relative inline-block">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-text-muted hover:bg-border"
      >
        +{count} ⋯
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-1 max-h-64 min-w-[180px] overflow-y-auto rounded-md border border-border bg-surface p-2 shadow-md">
          <div className="flex flex-wrap gap-1">
            {tags.map((t) => (
              <TagBadge key={t.id} tag={t} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface TagBadgeProps {
  tag: TagRead;
  onRemove?: () => void;
  style?: CSSProperties;
}

export function TagBadge({ tag, onRemove, style: externalStyle }: TagBadgeProps) {
  const colorStyle: CSSProperties | undefined = tag.color
    ? { color: tag.color, borderColor: tag.color, backgroundColor: 'transparent' }
    : undefined;

  if (onRemove) {
    return (
      <Badge
        variant="default"
        className={tag.color ? 'border' : undefined}
        style={colorStyle ?? externalStyle}
      >
        <span>{tag.name}</span>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-1 text-text-muted hover:text-danger"
          aria-label={`Удалить тег ${tag.name}`}
        >
          ×
        </button>
      </Badge>
    );
  }

  return (
    <Badge
      variant="default"
      className={tag.color ? 'border' : undefined}
      style={colorStyle ?? externalStyle}
    >
      {tag.name}
    </Badge>
  );
}