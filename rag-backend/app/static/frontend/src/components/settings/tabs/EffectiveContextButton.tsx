import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, Modal } from '@/components/ui';
import { api } from '@/api/client';
import type { CampaignId, EffectiveContextRead } from '@/api/types';

export function EffectiveContextButton({ campaignId }: EffectiveContextButtonProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
        Debug effective context
      </Button>
      {open && <EffectiveContextDialog campaignId={campaignId} onClose={() => setOpen(false)} />}
    </>
  );
}

interface EffectiveContextButtonProps {
  campaignId: CampaignId;
}

function EffectiveContextDialog({
  campaignId,
  onClose,
}: {
  campaignId: CampaignId;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ['effective-context', campaignId],
    queryFn: () => api.getEffectiveContext(campaignId),
  });

  return (
    <Modal open onClose={onClose} title="Effective Context" size="lg">
      <div className="p-4">
        {query.isLoading ? (
          <p className="text-sm text-text-muted">Загрузка…</p>
        ) : query.error ? (
          <p className="text-sm text-danger">Ошибка: {(query.error as Error).message}</p>
        ) : (
          <EffectiveContextView data={query.data} />
        )}
      </div>
    </Modal>
  );
}

function EffectiveContextView({ data }: { data: EffectiveContextRead | undefined }) {
  if (!data) return null;
  return (
    <div className="space-y-3">
      <div className="rounded border border-border bg-surface-2 p-3 text-xs">
        Всего токенов: <strong>{data.total_tokens.toLocaleString()}</strong>
        {data.budget != null && (
          <>
            {' '}/ бюджет <strong>{data.budget.toLocaleString()}</strong>
          </>
        )}
        {data.state_version != null && (
          <span className="ml-2 text-text-muted">
            (state_version: {data.state_version})
          </span>
        )}
        {data.truncated_fields && data.truncated_fields.length > 0 && (
          <div className="mt-1 text-warning">
            Усечены поля: {data.truncated_fields.join(', ')}
          </div>
        )}
      </div>
      <div className="max-h-96 space-y-2 overflow-y-auto">
        {data.blocks.map((b) => (
          <Card
            key={b.name}
            title={
              <span className="flex items-baseline gap-2">
                <span>{b.name}</span>
                <span className="text-xs font-normal text-text-muted">
                  ~{b.estimated_tokens.toLocaleString()} токенов
                </span>
              </span>
            }
          >
            {b.text ? (
              <pre className="whitespace-pre-wrap text-xs">{b.text}</pre>
            ) : (
              <p className="text-xs italic text-text-muted">(пусто)</p>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}