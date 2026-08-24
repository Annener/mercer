import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Card } from '@/components/ui';
import { api } from '@/api/client';
import { useChatStore } from '@/stores';
import { Markdown } from '@/components/chat/Markdown';
import type { UUID, UpdateModeSessionResponse, UpdateModeStateOp } from '@/api/types';

interface UpdateModePanelProps {
  chatId: UUID;
  onClose: () => void;
}

export function UpdateModePanel({ chatId, onClose }: UpdateModePanelProps) {
  const queryClient = useQueryClient();
  const sessionQuery = useQuery({
    queryKey: ['update-mode', chatId],
    queryFn: () => api.updateModeGetSession(chatId),
    refetchInterval: 5_000,
  });

  const [acceptedFileChanges, setAcceptedFileChanges] = useState<Set<string>>(new Set());
  const [rejectedFileChanges, setRejectedFileChanges] = useState<Set<string>>(new Set());
  const [acceptedOps, setAcceptedOps] = useState<Set<number>>(new Set());
  const [rejectedOps, setRejectedOps] = useState<Set<number>>(new Set());

  const reviewMutation = useMutation({
    mutationFn: () =>
      api.updateModeReview(
        chatId,
        Array.from(acceptedFileChanges),
        Array.from(rejectedFileChanges),
        {
          accepted_op_indexes: Array.from(acceptedOps),
          rejected_op_indexes: Array.from(rejectedOps),
          edited: [],
        },
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['update-mode', chatId] }),
  });

  const applyMutation = useMutation({
    mutationFn: () => api.updateModeApply(chatId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['update-mode', chatId] });
      void useChatStore.getState().loadChat(chatId);
      onClose();
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.updateModeCancel(chatId),
    onSuccess: () => onClose(),
  });

  if (!sessionQuery.data) {
    return null;
  }

  const session: UpdateModeSessionResponse = sessionQuery.data;

  const toggleFile = (id: string, accept: boolean) => {
    if (accept) {
      setAcceptedFileChanges((prev) => new Set(prev).add(id));
      setRejectedFileChanges((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    } else {
      setRejectedFileChanges((prev) => new Set(prev).add(id));
      setAcceptedFileChanges((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const toggleOp = (idx: number, accept: boolean) => {
    if (accept) {
      setAcceptedOps((prev) => new Set(prev).add(idx));
      setRejectedOps((prev) => {
        const next = new Set(prev);
        next.delete(idx);
        return next;
      });
    } else {
      setRejectedOps((prev) => new Set(prev).add(idx));
      setAcceptedOps((prev) => {
        const next = new Set(prev);
        next.delete(idx);
        return next;
      });
    }
  };

  return (
    <Card>
      <header className="-m-4 mb-3 flex items-center justify-between border-b border-border p-3">
        <div>
          <h3 className="text-base font-semibold">Update Mode — ревью</h3>
          <p className="text-xs text-text-muted">{session.note}</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => cancelMutation.mutate()}>
            Отменить
          </Button>
          <Button size="sm" onClick={() => reviewMutation.mutate()} disabled={reviewMutation.isPending}>
            Сохранить выбор
          </Button>
          <Button size="sm" onClick={() => applyMutation.mutate()} disabled={applyMutation.isPending}>
            Применить
          </Button>
        </div>
      </header>

      <div className="space-y-4">
        {session.file_changes.length > 0 && (
          <div>
            <h4 className="mb-2 text-sm font-semibold">Файловые изменения</h4>
            <div className="space-y-2">
              {session.file_changes.map((change) => (
                <div key={change.change_id} className="rounded border border-border p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <code className="text-xs">{change.file_path}</code>
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        variant={acceptedFileChanges.has(change.change_id) ? 'primary' : 'ghost'}
                        onClick={() => toggleFile(change.change_id, true)}
                      >
                        Принять
                      </Button>
                      <Button
                        size="sm"
                        variant={rejectedFileChanges.has(change.change_id) ? 'danger' : 'ghost'}
                        onClick={() => toggleFile(change.change_id, false)}
                      >
                        Отклонить
                      </Button>
                    </div>
                  </div>
                  <pre className="overflow-x-auto rounded bg-surface-2 p-2 text-xs">
                    {change.diff}
                  </pre>
                  {change.reasoning && (
                    <p className="mt-2 text-xs text-text-muted">{change.reasoning}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {session.state_ops.length > 0 && (
          <div>
            <h4 className="mb-2 text-sm font-semibold">Изменения state</h4>
            <div className="space-y-2">
              {session.state_ops.map((op) => (
                <StateOpRow
                  key={op.op_index}
                  op={op}
                  accepted={acceptedOps.has(op.op_index)}
                  rejected={rejectedOps.has(op.op_index)}
                  onToggle={(accept) => toggleOp(op.op_index, accept)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function StateOpRow({
  op,
  accepted,
  rejected,
  onToggle,
}: {
  op: UpdateModeStateOp;
  accepted: boolean;
  rejected: boolean;
  onToggle: (accept: boolean) => void;
}) {
  return (
    <div
      className={`rounded border p-3 ${
        op.is_destructive ? 'border-warning bg-warning/5' : 'border-border'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <p className="text-sm font-medium">{op.summary}</p>
          {op.from_text && (
            <p className="mt-1 text-xs text-text-muted">
              <span className="font-medium">Было:</span>{' '}
              <Markdown content={op.from_text} className="inline" />
            </p>
          )}
          {op.to_text && (
            <p className="mt-1 text-xs">
              <span className="font-medium">Станет:</span>{' '}
              <Markdown content={op.to_text} className="inline" />
            </p>
          )}
          {op.source_ref && (
            <p className="mt-1 text-xs text-text-muted">Основание: {op.source_ref}</p>
          )}
        </div>
        <div className="flex gap-1">
          <Button size="sm" variant={accepted ? 'primary' : 'ghost'} onClick={() => onToggle(true)}>
            Принять
          </Button>
          <Button size="sm" variant={rejected ? 'danger' : 'ghost'} onClick={() => onToggle(false)}>
            Отклонить
          </Button>
        </div>
      </div>
    </div>
  );
}