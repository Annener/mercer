import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, EmptyState, Modal, Checkbox, Badge } from '@/components/ui';
import { api } from '@/api/client';
import { Markdown } from '@/components/chat/Markdown';
import { basename } from '@/utils/path';
import type { CampaignId, Document, DocumentId, InitialProposalField } from '@/api/types';

interface InitialStateButtonProps {
  campaignId: CampaignId;
}

export function InitialStateButton({ campaignId }: InitialStateButtonProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Сформировать начальный контекст
      </Button>
      {open && <InitialStateWizard campaignId={campaignId} onClose={() => setOpen(false)} />}
    </>
  );
}

type Phase = 'select' | 'review' | 'result';

function InitialStateWizard({
  campaignId,
  onClose,
}: {
  campaignId: CampaignId;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<Phase>('select');
  const [selectedIds, setSelectedIds] = useState<DocumentId[]>([]);
  const [proposal, setProposal] = useState<{
    proposal_id: string;
    config_version: number;
    fields: InitialProposalField[];
  } | null>(null);

  // Tags → список документов
  const tagsQuery = useQuery({
    queryKey: ['campaign-tags', campaignId],
    queryFn: async () => {
      const own = await api.getCampaignTags(campaignId);
      const global = await api.getCampaignGlobalTags(campaignId);
      return [...own, ...global];
    },
  });

  const tagIds = tagsQuery.data?.map((t) => t.id) ?? [];
  const hasNoTags = tagsQuery.data && tagsQuery.data.length === 0;

  const documentsQuery = useQuery({
    queryKey: ['documents', 'by-tags', tagIds],
    queryFn: () =>
      api.getSettingsDocuments({ tagIds, status: 'indexed' }),
    enabled: tagIds.length > 0,
  });

  const previewMutation = useQuery({
    queryKey: ['initial-preview', campaignId, selectedIds],
    queryFn: () =>
      api.previewInitialState(campaignId, selectedIds, { propose_fields: true }),
    enabled: false,
  });

  const applyMutation = useQuery({
    queryKey: ['initial-apply', campaignId, proposal?.proposal_id],
    queryFn: () =>
      proposal
        ? api.applyInitialState(campaignId, proposal.proposal_id, proposal.config_version)
        : Promise.resolve(null),
    enabled: false,
  });

  return (
    <Modal open onClose={onClose} title="Initial State — формирование контекста" size="lg">
      <div className="p-4">
        {hasNoTags ? (
          <EmptyState
            title="Initial State недоступен"
            description="У кампании нет ни собственных, ни глобальных тегов. Прикрепите теги, чтобы формировать начальный контекст из индексированных документов."
          />
        ) : phase === 'select' ? (
          <SelectPhase
            documents={documentsQuery.data ?? []}
            selectedIds={selectedIds}
            onToggle={(id) => {
              setSelectedIds((prev) =>
                prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
              );
            }}
            onNext={async () => {
              const result = await previewMutation.refetch();
              if (result.data) {
                setProposal({
                  proposal_id: result.data.proposal_id,
                  config_version: result.data.config_version,
                  fields: result.data.proposal.fields,
                });
                setPhase('review');
              }
            }}
            loading={previewMutation.isFetching}
          />
        ) : phase === 'review' && proposal ? (
          <ReviewPhase
            fields={proposal.fields}
            onBack={() => setPhase('select')}
            onApply={async () => {
              const result = await applyMutation.refetch();
              if (result.data) {
                setPhase('result');
              }
            }}
            loading={applyMutation.isFetching}
          />
        ) : phase === 'result' ? (
          <ResultPhase onClose={onClose} />
        ) : null}
      </div>
    </Modal>
  );
}

function SelectPhase({
  documents,
  selectedIds,
  onToggle,
  onNext,
  loading,
}: {
  documents: Document[];
  selectedIds: DocumentId[];
  onToggle: (id: DocumentId) => void;
  onNext: () => void;
  loading: boolean;
}) {
  const totalTokens = selectedIds.length * 1000; // Примерная оценка, реальная — с бэкенда
  const budget = 64000;

  return (
    <div className="space-y-3">
      <p className="text-sm text-text-muted">
        Выберите документы для формирования начального контекста кампании.
      </p>
      <div className="rounded border border-border bg-surface-2 p-2 text-xs">
        Прогресс: {selectedIds.length} выбрано · ~{totalTokens.toLocaleString()} токенов
        {totalTokens > budget && <Badge variant="warning" className="ml-2">Превышение бюджета</Badge>}
      </div>
      <div className="max-h-96 space-y-1 overflow-y-auto rounded border border-border p-2">
        {documents.length === 0 ? (
          <p className="text-center text-sm text-text-muted">Нет документов</p>
        ) : (
          documents.map((d) => {
            const id = d.id ?? d.document_id;
            if (!id) return null;
            const name = d.title || basename(d.source_path ?? d.path);
            return (
              <label key={id} className="flex cursor-pointer items-center gap-2 rounded p-1 hover:bg-surface">
                <Checkbox
                  checked={selectedIds.includes(id)}
                  onChange={() => onToggle(id)}
                />
                <span className="text-sm">{name}</span>
              </label>
            );
          })
        )}
      </div>
      <div className="flex justify-end gap-2">
        <Button onClick={onNext} disabled={selectedIds.length === 0 || loading}>
          {loading ? 'Загрузка…' : 'Сформировать proposal →'}
        </Button>
      </div>
    </div>
  );
}

function ReviewPhase({
  fields,
  onBack,
  onApply,
  loading,
}: {
  fields: InitialProposalField[];
  onBack: () => void;
  onApply: () => void;
  loading: boolean;
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-text-muted">
        Проверьте предложенные значения. Можно редактировать перед применением.
      </p>
      <div className="max-h-96 space-y-2 overflow-y-auto">
        {fields.map((f) => (
          <Card key={f.field_key} title={`${f.field_key} (${f.status})`}>
            {f.single_value ? (
              <Markdown content={f.single_value.text} />
            ) : f.list_value ? (
              <ul className="list-inside list-disc">
                {f.list_value.items.map((item, i) => (
                  <li key={i}>
                    <Markdown content={item.text} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs italic text-text-muted">пусто</p>
            )}
          </Card>
        ))}
      </div>
      <div className="flex justify-between gap-2">
        <Button variant="ghost" onClick={onBack}>
          ← Назад
        </Button>
        <Button onClick={onApply} disabled={loading}>
          {loading ? 'Применение…' : 'Применить'}
        </Button>
      </div>
    </div>
  );
}

function ResultPhase({ onClose }: { onClose: () => void }) {
  return (
    <div className="space-y-3 text-center">
      <h3 className="text-lg font-semibold text-success">Initial State применён</h3>
      <p className="text-sm text-text-muted">
        Кампания теперь использует начальный контекст.
      </p>
      <Button onClick={onClose}>Закрыть</Button>
    </div>
  );
}