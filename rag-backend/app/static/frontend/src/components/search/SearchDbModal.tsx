import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Field, Input, Modal, Select, SelectWrapper } from '@/components/ui';
import { api } from '@/api/client';
import { useDomainStore } from '@/stores';
import { Markdown } from '@/components/chat/Markdown';
import type { DomainId, SearchResult } from '@/api/types';

interface SearchDbModalProps {
  open: boolean;
  onClose: () => void;
}

export function SearchDbModal({ open, onClose }: SearchDbModalProps) {
  const domains = useDomainStore((s) => s.domains);
  const [domainId, setDomainId] = useState<DomainId | ''>(domains[0]?.domain_id ?? '');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(20);
  const [submitted, setSubmitted] = useState<{ domainId: DomainId; query: string; limit: number } | null>(null);

  const searchQuery = useQuery({
    queryKey: ['db-search', submitted],
    queryFn: () =>
      submitted
        ? api.textSearchByDomain(submitted.domainId, submitted.query, submitted.limit)
        : Promise.resolve<SearchResult[]>([]),
    enabled: !!submitted,
  });

  const filteredDomains = domains.filter((d) => d.domain_id !== 'default');

  return (
    <Modal open={open} onClose={onClose} title="Поиск по хранилищу" size="lg">
      <div className="space-y-3 p-4">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Домен:">
            <SelectWrapper>
              <Select
                value={domainId}
                onChange={(e) => setDomainId(e.target.value as DomainId | '')}
                options={filteredDomains.map((d) => ({ value: d.domain_id, label: d.display_name ?? d.domain_id }))}
              />
            </SelectWrapper>
          </Field>
          <Field label="Запрос:" className="flex-1">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && query && domainId) {
                  setSubmitted({ domainId: domainId as DomainId, query, limit });
                }
              }}
              placeholder="Введите текст…"
            />
          </Field>
          <Field label="Лимит:">
            <Input
              type="number"
              value={limit}
              min={1}
              max={200}
              onChange={(e) => setLimit(Number(e.target.value))}
            />
          </Field>
          <Button
            onClick={() => query && domainId && setSubmitted({ domainId: domainId as DomainId, query, limit })}
            disabled={!query || !domainId}
          >
            Найти
          </Button>
        </div>

        <div className="max-h-96 space-y-2 overflow-y-auto">
          {searchQuery.isFetching && (
            <p className="text-sm text-text-muted">Поиск…</p>
          )}
          {searchQuery.data?.length === 0 && submitted && !searchQuery.isFetching && (
            <p className="text-sm text-text-muted">Ничего не найдено</p>
          )}
          {searchQuery.data?.map((r, i) => (
            <article key={i} className="rounded border border-border p-3">
              <header className="mb-2 flex items-center justify-between">
                <code className="text-xs">{r.path ?? r.document_id}</code>
                {r.page != null && (
                  <span className="text-xs text-text-muted">стр. {r.page}</span>
                )}
              </header>
              <Markdown content={r.text} />
              {r.score != null && (
                <p className="mt-1 text-xs text-text-muted">Score: {r.score.toFixed(3)}</p>
              )}
            </article>
          ))}
        </div>
      </div>
    </Modal>
  );
}