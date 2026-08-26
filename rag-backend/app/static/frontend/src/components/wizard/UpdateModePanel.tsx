import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Card } from '@/components/ui';
import { api } from '@/api/client';
import { useChatStore } from '@/stores';
import { Markdown } from '@/components/chat/Markdown';
import type {
  UUID,
  UpdateModeSessionResponse,
  UpdateModeStateFieldChangeEntry,
  UpdateModeStatePatchEntry,
} from '@/api/types';

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
  const [acceptedFieldOps, setAcceptedFieldOps] = useState<Set<number>>(new Set());
  const [rejectedFieldOps, setRejectedFieldOps] = useState<Set<number>>(new Set());
  const [applied, setApplied] = useState<boolean>(false);

  const applyMutation = useMutation({
    mutationFn: async () => {
      // Persist accept/reject decisions via PATCH /review before applying.
      // Without this step the backend treats every op as 'pending' and
      // POST /apply returns 422 "No accepted changes to apply".
      await api.updateModeReview(
        chatId,
        Array.from(acceptedFileChanges),
        Array.from(rejectedFileChanges),
        {
          accepted_op_indexes: Array.from(acceptedOps),
          rejected_op_indexes: Array.from(rejectedOps),
          edited: [],
        },
        {
          accepted_op_indexes: Array.from(acceptedFieldOps),
          rejected_op_indexes: Array.from(rejectedFieldOps),
        },
      );
      return api.updateModeApply(chatId);
    },
    onSuccess: () => {
      setApplied(true);
      void queryClient.invalidateQueries({ queryKey: ['update-mode', chatId] });
      void useChatStore.getState().loadChat(chatId);
    },
    onError: (err) => {
      void queryClient.invalidateQueries({ queryKey: ['update-mode', chatId] });
      console.error('Update Mode apply failed:', err);
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
  const fileChanges = session.changes ?? [];
  const stateOps = session.state_patch_operations ?? [];
  const fieldOps = session.state_field_change_operations ?? [];
  const warnings = session.warnings ?? [];
  const relatedDocIds = session.related_document_ids ?? [];

  const note = warnings[0] ?? 'Предложение обновления контекста кампании';

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

  const toggleFieldOp = (idx: number, accept: boolean) => {
    if (accept) {
      setAcceptedFieldOps((prev) => new Set(prev).add(idx));
      setRejectedFieldOps((prev) => {
        const next = new Set(prev);
        next.delete(idx);
        return next;
      });
    } else {
      setRejectedFieldOps((prev) => new Set(prev).add(idx));
      setAcceptedFieldOps((prev) => {
        const next = new Set(prev);
        next.delete(idx);
        return next;
      });
    }
  };

  return (
    <Card>
      <header className="-m-4 mb-3 border-b border-border p-3">
        <h3 className="text-base font-semibold">Update Mode — ревью</h3>
        <p className="text-xs text-text-muted">{note}</p>
      </header>

      <div className="space-y-4">
        {!applied && fileChanges.length > 0 && (
          <div>
            <h4 className="mb-2 text-sm font-semibold">Файловые изменения</h4>
            <div className="space-y-2">
              {fileChanges.map((change) => (
                <div key={change.change_id} className="rounded border border-border p-3">
                  {change.description && (
                    <p className="mb-2 text-sm font-semibold text-text">
                      {change.description}
                    </p>
                  )}
                  <div className="mb-2 flex items-center justify-between">
                    <code className="text-xs">
                      {change.file_path ?? '(путь не указан)'}
                    </code>
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
                  {change.unified_diff && <DiffView text={change.unified_diff} />}
                </div>
              ))}
            </div>
          </div>
        )}

        {!applied && fieldOps.length > 0 && (
          <div>
            <h4 className="mb-2 text-sm font-semibold">Изменения схемы</h4>
            <div className="space-y-2">
              {fieldOps.map((op) => (
                <SchemaChangeRow
                  key={op.op_index}
                  op={op}
                  accepted={acceptedFieldOps.has(op.op_index)}
                  rejected={rejectedFieldOps.has(op.op_index)}
                  onToggle={(accept) => toggleFieldOp(op.op_index, accept)}
                />
              ))}
            </div>
          </div>
        )}

        {!applied && stateOps.length > 0 && (
          <div>
            <h4 className="mb-2 text-sm font-semibold">Изменения state</h4>
            <div className="space-y-2">
              {stateOps.map((op) => (
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

        {applied && (
          <SourcesRefreshBlock
            relatedDocumentIds={relatedDocIds}
            applied={applied}
            onDismiss={onClose}
          />
        )}
      </div>

      <footer className="-m-4 mt-3 flex items-center justify-end gap-2 border-t border-border p-3">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => cancelMutation.mutate()}
          disabled={cancelMutation.isPending}
        >
          Отменить
        </Button>
        <Button
          size="sm"
          onClick={() => applyMutation.mutate()}
          disabled={
            applyMutation.isPending ||
            applied ||
            (acceptedFileChanges.size === 0 &&
              rejectedFileChanges.size === 0 &&
              acceptedOps.size === 0 &&
              rejectedOps.size === 0 &&
              acceptedFieldOps.size === 0 &&
              rejectedFieldOps.size === 0)
          }
        >
          {applyMutation.isPending ? 'Применение…' : 'Применить'}
        </Button>
      </footer>
    </Card>
  );
}

function DiffView({ text }: { text: string }) {
  return (
    <div className="max-h-96 overflow-auto rounded bg-surface-2 p-2 font-mono text-xs">
      {text.split('\n').map((line, idx) => {
        let cls = 'text-text';
        if (line.startsWith('+')) {
          cls = 'bg-success/10 text-success';
        } else if (line.startsWith('-')) {
          cls = 'bg-danger/10 text-danger';
        } else if (line.startsWith('@@')) {
          cls = 'text-text-muted';
        }
        return (
          <div
            key={idx}
            className={`whitespace-pre-wrap break-words ${cls}`}
          >
            {line || ' '}
          </div>
        );
      })}
    </div>
  );
}

function SourcesRefreshBlock({
  relatedDocumentIds,
  applied,
  onDismiss,
}: {
  relatedDocumentIds: string[];
  applied: boolean;
  onDismiss: () => void;
}) {
  const message = applied
    ? 'Изменения применены. Теперь можно актуализировать связанные источники (markdown-файлы), чтобы они отразили новые значения полей.'
    : 'В этом proposal есть связанные источники. После применения изменений их можно актуализировать одним нажатием.';
  return (
    <div
      data-s-sources-refresh
      className="rounded border border-accent/30 bg-accent/5 p-3"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-text">Актуализация источников</h4>
          <p className="mt-1 text-xs text-text-muted">
            {message}
          </p>
          {relatedDocumentIds.length > 0 && (
            <p className="mt-1 text-xs text-text-muted">
              Связанных документов: <strong>{relatedDocumentIds.length}</strong>
            </p>
          )}
        </div>
        <Button size="sm" variant="ghost" onClick={onDismiss}>
          Закрыть
        </Button>
      </div>
      <Button
        size="sm"
        disabled
        title="Цикл актуализации появится в следующей итерации"
      >
        Актуализировать
      </Button>
    </div>
  );
}

function StateOpRow({
  op,
  accepted,
  rejected,
  onToggle,
}: {
  op: UpdateModeStatePatchEntry;
  accepted: boolean;
  rejected: boolean;
  onToggle: (accept: boolean) => void;
}) {
  const summary = `${op.field_label} (${op.field_key}) — ${op.operation}`;
  const isDestructive =
    op.operation === 'clear_single' || op.operation === 'remove_list_item';
  return (
    <div
      className={`rounded border p-3 ${
        isDestructive ? 'border-warning bg-warning/5' : 'border-border'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <p className="text-sm font-medium">{summary}</p>
          {op.previous_text && (
            <p className="mt-1 text-xs text-text-muted">
              <span className="font-medium">Было:</span>{' '}
              <Markdown content={op.previous_text} className="inline" />
            </p>
          )}
          {op.proposed_text && (
            <p className="mt-1 text-xs">
              <span className="font-medium">Станет:</span>{' '}
              <Markdown content={op.proposed_text} className="inline" />
            </p>
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

function SchemaChangeRow({
  op,
  accepted,
  rejected,
  onToggle,
}: {
  op: UpdateModeStateFieldChangeEntry;
  accepted: boolean;
  rejected: boolean;
  onToggle: (accept: boolean) => void;
}) {
  const isCreate = op.operation === 'create_field';
  const summary = isCreate
    ? `Создать поле: ${op.proposed_label ?? op.key} (${op.key})`
    : `Обновить поле: ${op.key}`;
  const proposedDetails: string[] = [];
  if (op.proposed_label) proposedDetails.push(`label: «${op.proposed_label}»`);
  if (op.proposed_mode) proposedDetails.push(`mode: ${op.proposed_mode}`);
  if (op.proposed_description) proposedDetails.push(`description: «${op.proposed_description}»`);
  return (
    <div className="rounded border border-border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <p className="text-sm font-medium">{summary}</p>
          {op.previous_label && (
            <p className="mt-1 text-xs text-text-muted">
              <span className="font-medium">Было:</span> «{op.previous_label}»
            </p>
          )}
          {proposedDetails.length > 0 && (
            <p className="mt-1 text-xs">
              <span className="font-medium">Станет:</span> {proposedDetails.join(', ')}
            </p>
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