import { useMemo, useState } from 'react';
import { Button, Checkbox, Badge } from '@/components/ui';
import { basename } from '@/utils/path';
import type { Document } from '@/api/types';
import {
  PER_DOC_TOKEN_LIMIT,
  TOTAL_TOKEN_BUDGET,
  formatTokens,
  pluralRu,
} from './constants';

export interface SelectDocumentsStepProps {
  documents: Document[];
  documentsLoading: boolean;
  documentsError: string | null;
  selectedIds: string[];
  onToggle: (id: string) => void;
  onNext: () => void;
  loading: boolean;
  hintTagCount?: number;
}

function docTitle(d: Document): string {
  return d.title || basename(d.source_path ?? d.path);
}

function isOversized(d: Document): boolean {
  return (
    typeof d.estimated_tokens === 'number' &&
    d.estimated_tokens > PER_DOC_TOKEN_LIMIT
  );
}

export function SelectDocumentsStep({
  documents,
  documentsLoading,
  documentsError,
  selectedIds,
  onToggle,
  onNext,
  loading,
  hintTagCount,
}: SelectDocumentsStepProps) {
  const [search, setSearch] = useState('');

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const docsById = useMemo(() => {
    const m = new Map<string, Document>();
    for (const d of documents) {
      const id = d.id ?? d.document_id;
      if (id) m.set(String(id), d);
    }
    return m;
  }, [documents]);

  const selectedTokens = useMemo(() => {
    let total = 0;
    for (const id of selectedIds) {
      const d = docsById.get(String(id));
      if (d && typeof d.estimated_tokens === 'number') {
        total += d.estimated_tokens;
      }
    }
    return total;
  }, [selectedIds, docsById]);

  const overBudget = selectedTokens > TOTAL_TOKEN_BUDGET;
  const pct = Math.min(
    100,
    Math.round((selectedTokens / TOTAL_TOKEN_BUDGET) * 100),
  );

  const filteredDocs = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return documents;
    return documents.filter((d) => {
      const title = docTitle(d).toLowerCase();
      const path = (d.source_path ?? '').toLowerCase();
      return title.includes(q) || path.includes(q);
    });
  }, [documents, search]);

  const tagsHint =
    typeof hintTagCount === 'number' && hintTagCount > 0 ? (
      <p className="text-xs text-text-muted">
        Показаны только документы, привязанные к тегам кампании (
        {hintTagCount} {pluralRu(hintTagCount, ['тег', 'тега', 'тегов'])}).
      </p>
    ) : null;

  const canNext = selectedIds.length > 0 && !overBudget && !loading;

  return (
    <div className="flex flex-col gap-3" data-select-step>
      <p className="text-sm text-text-muted">
        Выберите Markdown-документы для формирования Initial State. Лимит на
        документ: {formatTokens(PER_DOC_TOKEN_LIMIT)} токенов; общий бюджет:{' '}
        {formatTokens(TOTAL_TOKEN_BUDGET)}.
      </p>
      {tagsHint}

      <input
        type="search"
        placeholder="Поиск по названию или пути…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full rounded border border-border bg-surface-2 px-3 py-2 text-sm outline-none focus:border-primary"
        data-search
      />

      <div className="max-h-96 space-y-1 overflow-y-auto rounded border border-border p-2">
        {documentsError ? (
          <p className="px-2 py-3 text-sm text-danger">
            Не удалось загрузить документы: {documentsError}
          </p>
        ) : documentsLoading ? (
          <p className="px-2 py-3 text-center text-sm text-text-muted">
            Загрузка документов…
          </p>
        ) : filteredDocs.length === 0 ? (
          <p className="px-2 py-3 text-center text-sm text-text-muted">
            Нет подходящих Markdown-документов.
          </p>
        ) : (
          filteredDocs.map((d) => {
            const id = String(d.id ?? d.document_id ?? '');
            if (!id) return null;
            const oversized = isOversized(d);
            const disabled = oversized;
            const checked = selectedSet.has(id);
            return (
              <label
                key={id}
                className={
                  'flex cursor-pointer items-start gap-2 rounded p-2 hover:bg-surface ' +
                  (disabled ? 'cursor-not-allowed opacity-60 hover:bg-transparent' : '')
                }
                data-doc-id={id}
              >
                <Checkbox
                  checked={checked}
                  onChange={() => onToggle(id)}
                  disabled={disabled}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {docTitle(d)}
                  </div>
                  {d.source_path && (
                    <div
                      className="truncate font-mono text-xs text-text-muted"
                      title={d.source_path}
                      data-doc-path
                    >
                      {d.source_path}
                    </div>
                  )}
                  {disabled && (
                    <div className="mt-1 text-xs text-warning">
                      Документ слишком большой для Initial State (&gt;{' '}
                      {formatTokens(PER_DOC_TOKEN_LIMIT)} ток.)
                    </div>
                  )}
                </div>
                <div
                  className="shrink-0 font-mono text-xs tabular-nums text-text-muted"
                  data-doc-tokens
                >
                  {formatTokens(d.estimated_tokens)} ток.
                </div>
              </label>
            );
          })
        )}
      </div>

      <div className="flex flex-col gap-2 rounded border border-border bg-surface-2 p-3">
        <div className="flex items-center justify-between text-xs">
          <span className="text-text-muted">Выбрано:</span>
          <span className="font-mono tabular-nums" data-testid="budget-selected">
            <strong>{selectedIds.length}</strong> док. / {formatTokens(selectedTokens)} ток.
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-border">
          <div
            className={
              'h-full transition-all ' +
              (overBudget ? 'bg-danger' : 'bg-primary')
            }
            style={{ width: `${pct}%` }}
            data-testid="budget-fill"
          />
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="font-mono tabular-nums text-text-muted" data-testid="budget-fraction">
            {formatTokens(selectedTokens)} / {formatTokens(TOTAL_TOKEN_BUDGET)}
          </span>
          {overBudget && (
            <Badge variant="warning" data-budget-over>
              Превышение бюджета
            </Badge>
          )}
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <Button
          onClick={onNext}
          disabled={!canNext}
          data-testid="next-button"
        >
          {loading ? 'Загрузка…' : 'Далее →'}
        </Button>
      </div>
    </div>
  );
}
