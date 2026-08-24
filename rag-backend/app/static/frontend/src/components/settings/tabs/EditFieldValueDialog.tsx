import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  ConfirmModal,
  EmptyState,
  Field,
  Input,
  Modal,
  Textarea,
} from '@/components/ui';
import { api, HttpError } from '@/api/client';
import { InitialStateButton } from './InitialStateButton';
import type {
  CampaignId,
  CampaignStateFieldValue,
  CampaignStateListItemRead,
  CampaignStatePatchFailure,
  CampaignStatePatchOp,
  CampaignStateVersion,
  StateFieldConfig,
} from '@/api/types';

const MANUAL_REASON = 'manual edit from settings';

interface EditFieldValueDialogProps {
  open: boolean;
  campaignId: CampaignId;
  field: StateFieldConfig;
  onClose: () => void;
  onSaved: () => void;
}

export function EditFieldValueDialog({
  open,
  campaignId,
  field,
  onClose,
  onSaved,
}: EditFieldValueDialogProps) {
  const stateQuery = useQuery({
    queryKey: ['active-state', campaignId],
    queryFn: () => api.getActiveCampaignState(campaignId),
  });

  const currentValue = findFieldValue(stateQuery.data, field.key);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Редактирование поля «${field.label}»`}
      size="md"
    >
      <div className="p-4">
        {stateQuery.isLoading ? (
          <p className="text-sm text-text-muted">Загрузка активного state…</p>
        ) : stateQuery.error ? (
          <p className="text-sm text-danger">
            Не удалось загрузить state: {(stateQuery.error as Error).message}
          </p>
        ) : stateQuery.data == null ? (
          <EmptyState
            title="Нет активной версии state"
            description="Сначала примените Initial State для кампании — после этого можно будет редактировать значения полей."
            actions={<InitialStateButton campaignId={campaignId} />}
          />
        ) : field.mode === 'single' ? (
          <SingleEditor
            campaignId={campaignId}
            field={field}
            current={currentValue}
            version={stateQuery.data}
            onClose={onClose}
            onSaved={onSaved}
          />
        ) : (
          <ListEditor
            campaignId={campaignId}
            field={field}
            current={currentValue}
            version={stateQuery.data}
            onClose={onClose}
            onSaved={onSaved}
          />
        )}
      </div>
    </Modal>
  );
}

function findFieldValue(
  version: CampaignStateVersion | null | undefined,
  fieldKey: string,
): CampaignStateFieldValue | undefined {
  return version?.fields?.find((f) => f.field_key === fieldKey);
}

interface EditorBaseProps {
  campaignId: CampaignId;
  field: StateFieldConfig;
  current: CampaignStateFieldValue | undefined;
  version: CampaignStateVersion;
  onClose: () => void;
  onSaved: () => void;
}

function SingleEditor({
  campaignId,
  field,
  current,
  version,
  onClose,
  onSaved,
}: EditorBaseProps) {
  const queryClient = useQueryClient();
  const initialText = current?.single_value?.text ?? '';
  const [text, setText] = useState(initialText);
  const [error, setError] = useState<string | null>(null);
  const [failures, setFailures] = useState<CampaignStatePatchFailure[]>([]);
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    setText(initialText);
    setError(null);
    setFailures([]);
    setConfirmClear(false);
  }, [field.key, initialText]);

  const isDirty = text !== initialText;
  const hasOriginalValue = Boolean(initialText);

  const mutation = useMutation({
    mutationFn: (ops: CampaignStatePatchOp[]) =>
      api.patchCampaignState(campaignId, {
        base_state_version: version.summary.state_version,
        config_version: version.summary.config_version,
        operations: ops,
      }),
    onSuccess: (resp) => {
      setError(null);
      if (resp.failed_operations.length > 0) {
        setFailures(resp.failed_operations);
        return;
      }
      void queryClient.invalidateQueries({ queryKey: ['active-state', campaignId] });
      onSaved();
    },
    onError: (err) => {
      setFailures([]);
      setError(
        err instanceof HttpError ? err.message : 'Не удалось сохранить значение',
      );
    },
  });

  const submitReplace = () => {
    setError(null);
    setFailures([]);
    if (!text.trim()) return;
    mutation.mutate([
      {
        type: 'replace_single',
        field_key: field.key,
        text: text.trim(),
        reason: MANUAL_REASON,
      },
    ]);
  };

  const submitClear = () => {
    setConfirmClear(false);
    setError(null);
    setFailures([]);
    mutation.mutate([
      {
        type: 'clear_single',
        field_key: field.key,
        reason: MANUAL_REASON,
      },
    ]);
  };

  return (
    <div className="space-y-3">
      <div className="text-xs text-text-muted">
        <code>{field.key}</code> · single · state_version={version.summary.state_version},
        config_version={version.summary.config_version}
      </div>

      <Field label="Текущее значение">
        <Textarea
          rows={6}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={hasOriginalValue ? '' : '(пусто)'}
          className="font-mono text-xs"
        />
      </Field>

      {failures.length > 0 && <FailureList failures={failures} />}
      {error && (
        <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}

      <div className="flex justify-between gap-2 border-t border-border pt-3">
        <Button
          variant="danger"
          disabled={!hasOriginalValue || mutation.isPending}
          onClick={() => setConfirmClear(true)}
        >
          Очистить
        </Button>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            Отмена
          </Button>
          <Button
            disabled={!isDirty || !text.trim() || mutation.isPending}
            loading={mutation.isPending}
            onClick={submitReplace}
          >
            Сохранить
          </Button>
        </div>
      </div>

      <ConfirmModal
        open={confirmClear}
        title="Очистить поле?"
        message={
          <>
            Будет применена операция <code>clear_single</code> для поля{' '}
            <code>{field.key}</code>. Создастся новая версия state.
          </>
        }
        confirmLabel="Очистить"
        pending={mutation.isPending}
        onConfirm={submitClear}
        onClose={() => setConfirmClear(false)}
      />
    </div>
  );
}

function ListEditor({
  campaignId,
  field,
  current,
  version,
  onClose,
  onSaved,
}: EditorBaseProps) {
  const queryClient = useQueryClient();
  const initialItems = useMemo<CampaignStateListItemRead[]>(
    () => current?.items ?? [],
    [current],
  );
  const [items, setItems] = useState<EditableItem[]>(() =>
    initialItems.map(toEditable),
  );
  const [error, setError] = useState<string | null>(null);
  const [failures, setFailures] = useState<CampaignStatePatchFailure[]>([]);
  const [confirmRemoveKey, setConfirmRemoveKey] = useState<string | null>(null);

  useEffect(() => {
    setItems(initialItems.map(toEditable));
    setError(null);
    setFailures([]);
    setConfirmRemoveKey(null);
  }, [field.key, initialItems]);

  const ops: CampaignStatePatchOp[] = useMemo(
    () => buildOps(field.key, items),
    [field.key, items],
  );

  const mutation = useMutation({
    mutationFn: () =>
      api.patchCampaignState(campaignId, {
        base_state_version: version.summary.state_version,
        config_version: version.summary.config_version,
        operations: ops,
      }),
    onSuccess: (resp) => {
      setError(null);
      if (resp.failed_operations.length > 0) {
        setFailures(resp.failed_operations);
        return;
      }
      void queryClient.invalidateQueries({ queryKey: ['active-state', campaignId] });
      onSaved();
    },
    onError: (err) => {
      setFailures([]);
      setError(
        err instanceof HttpError ? err.message : 'Не удалось сохранить список',
      );
    },
  });

  const isDirty = ops.length > 0;
  const addNew = (raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed) return;
    setItems((prev) => [
      ...prev,
      {
        item_key: `new_${Date.now()}_${prev.length}`,
        text: trimmed,
        resolved: false,
        dirty: false,
        resolveDirty: false,
        removed: false,
        isNew: true,
      },
    ]);
  };

  return (
    <div className="space-y-3">
      <div className="text-xs text-text-muted">
        <code>{field.key}</code> · list · state_version={version.summary.state_version},
        config_version={version.summary.config_version}
      </div>

      <ul className="space-y-2">
        {items.length === 0 && (
          <li className="rounded border border-dashed border-border p-3 text-xs text-text-muted">
            Список пуст. Добавьте первый элемент ниже.
          </li>
        )}
        {items.map((it) => (
          <li
            key={it.item_key}
            className={`flex items-start gap-2 rounded border p-2 ${
              it.removed
                ? 'border-danger/30 bg-danger/5 opacity-60'
                : it.dirty || it.resolveDirty
                  ? 'border-warning/40 bg-warning/5'
                  : 'border-border'
            }`}
          >
            <div className="flex-1 space-y-1">
              <Input
                value={it.text}
                onChange={(e) =>
                  setItems((prev) =>
                    prev.map((p) =>
                      p.item_key === it.item_key
                        ? { ...p, text: e.target.value, dirty: !p.isNew && p.text !== e.target.value }
                        : p,
                    ),
                  )
                }
                placeholder="Текст элемента"
                className="font-mono text-xs"
                disabled={it.removed}
              />
              <div className="flex items-center gap-2 text-xs text-text-muted">
                <code>{it.item_key}</code>
                {it.resolved && !it.resolveDirty && <span className="text-success">решён</span>}
                {it.resolveDirty && (
                  <span className="text-warning">
                    {it.resolved ? 'пометить решённым' : 'снять отметку "решён"'}
                  </span>
                )}
                {it.dirty && <span className="text-warning">изменён</span>}
                {it.removed && <span className="text-danger">будет удалён</span>}
                {it.isNew && !it.removed && <span className="text-success">новый</span>}
              </div>
            </div>
            <div className="flex flex-col gap-1">
              {!it.removed && (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setItems((prev) =>
                        prev.map((p) =>
                          p.item_key === it.item_key
                            ? { ...p, resolved: !p.resolved, resolveDirty: true }
                            : p,
                        ),
                      )
                    }
                  >
                    {it.resolved ? 'Снять решение' : 'Решить'}
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => setConfirmRemoveKey(it.item_key)}
                  >
                    Удалить
                  </Button>
                </>
              )}
              {it.removed && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setItems((prev) =>
                      prev.map((p) =>
                        p.item_key === it.item_key ? { ...p, removed: false } : p,
                      ),
                    )
                  }
                >
                  Отменить
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>

      <NewItemForm onAdd={addNew} disabled={mutation.isPending} />

      {failures.length > 0 && <FailureList failures={failures} />}
      {error && (
        <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}

      <div className="flex justify-end gap-2 border-t border-border pt-3">
        <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
          Отмена
        </Button>
        <Button
          disabled={!isDirty || mutation.isPending}
          loading={mutation.isPending}
          onClick={() => {
            setError(null);
            setFailures([]);
            mutation.mutate();
          }}
        >
          Сохранить всё
        </Button>
      </div>

      <ConfirmModal
        open={confirmRemoveKey !== null}
        title="Удалить элемент?"
        message={
          <>
            Элемент <code>{confirmRemoveKey}</code> будет помечен на удаление. Создастся новая версия
            state.
          </>
        }
        confirmLabel="Удалить"
        pending={false}
        onConfirm={() => {
          if (confirmRemoveKey) {
            setItems((prev) =>
              prev.map((p) =>
                p.item_key === confirmRemoveKey ? { ...p, removed: true } : p,
              ),
            );
          }
          setConfirmRemoveKey(null);
        }}
        onClose={() => setConfirmRemoveKey(null)}
      />
    </div>
  );
}

function NewItemForm({
  onAdd,
  disabled,
}: {
  onAdd: (text: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState('');
  return (
    <div className="flex items-end gap-2 rounded border border-border p-2">
      <Field label="Новый элемент" className="flex-1">
        <Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Текст нового элемента"
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && value.trim()) {
              e.preventDefault();
              onAdd(value);
              setValue('');
            }
          }}
        />
      </Field>
      <Button
        size="sm"
        disabled={!value.trim() || disabled}
        onClick={() => {
          onAdd(value);
          setValue('');
        }}
      >
        + Добавить
      </Button>
    </div>
  );
}

interface EditableItem {
  item_key: string;
  text: string;
  resolved: boolean;
  dirty: boolean;
  resolveDirty: boolean;
  removed: boolean;
  isNew: boolean;
}

function toEditable(item: CampaignStateListItemRead): EditableItem {
  return {
    item_key: item.item_key,
    text: item.text,
    resolved: item.resolved,
    dirty: false,
    resolveDirty: false,
    removed: false,
    isNew: false,
  };
}

function buildOps(fieldKey: string, items: EditableItem[]): CampaignStatePatchOp[] {
  const ops: CampaignStatePatchOp[] = [];
  for (const it of items) {
    if (it.removed && !it.isNew) {
      ops.push({
        type: 'remove_list_item',
        field_key: fieldKey,
        item_key: it.item_key,
        reason: MANUAL_REASON,
      });
      continue;
    }
    if (it.isNew && !it.removed) {
      ops.push({
        type: 'add_list_item',
        field_key: fieldKey,
        text: it.text,
        reason: MANUAL_REASON,
      });
      continue;
    }
    if (it.dirty && it.text.trim()) {
      ops.push({
        type: 'update_list_item',
        field_key: fieldKey,
        item_key: it.item_key,
        text: it.text.trim(),
        reason: MANUAL_REASON,
      });
    }
    if (it.resolveDirty && it.resolved) {
      ops.push({
        type: 'resolve_list_item',
        field_key: fieldKey,
        item_key: it.item_key,
        reason: MANUAL_REASON,
      });
    }
  }
  return ops;
}

function FailureList({ failures }: { failures: CampaignStatePatchFailure[] }) {
  return (
    <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
      <div className="font-semibold">Не все операции применены:</div>
      <ul className="mt-1 list-disc pl-4">
        {failures.map((f) => (
          <li key={f.op_index}>
            #{f.op_index} {f.op_type} — {f.code}
            {f.detail ? `: ${f.detail}` : ''}
          </li>
        ))}
      </ul>
    </div>
  );
}