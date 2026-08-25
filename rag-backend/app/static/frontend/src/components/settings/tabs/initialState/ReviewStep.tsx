import { useMemo, useState, type ReactNode } from 'react';
import { Button } from '@/components/ui';
import { Markdown } from '@/components/chat/Markdown';
import { clsx } from '@/components/ui';
import type {
  DocumentSnapshot,
  InitialProposal,
  InitialProposalField,
  InitialFieldStatus,
} from '@/api/types';
import type { WizardError } from './constants';
import type { SuggestedFieldUiState } from './suggestedFieldState';

export type { SuggestedFieldUiState };

export interface ReviewStepProps {
  proposal: InitialProposal;
  sourceSnapshot: DocumentSnapshot[];
  suggestedFields: SuggestedFieldUiState[];
  warnings?: string[];
  onBack: () => void;
  onApply: () => void;
  onSuggestedFieldChange: (
    index: number,
    patch: Partial<SuggestedFieldUiState>,
  ) => void;
  onToggleSuggestedFieldAccept: (index: number) => void;
  error?: WizardError | null;
  onDismissError?: () => void;
  loading?: boolean;
}

const FIELD_KEY_REGEX = /^[a-z][a-z0-9_]{0,63}$/;

function snapshotMap(snapshots: DocumentSnapshot[]) {
  const m = new Map<string, DocumentSnapshot>();
  for (const s of snapshots) {
    m.set(`file:${s.document_id}:sha:${s.content_sha}`, s);
  }
  return m;
}

function refLabel(ref: string, snapshotById: Map<string, DocumentSnapshot>): string {
  const snap = snapshotById.get(ref);
  if (!snap) return ref;
  return snap.title || snap.source_path || snap.document_id;
}

function statusLabel(s: InitialFieldStatus): string {
  if (s === 'proposed') return 'предложено';
  if (s === 'needs_clarification') return 'требуется уточнение';
  return 'нет данных';
}

function statusVariant(s: InitialFieldStatus): 'success' | 'warning' | 'default' {
  if (s === 'proposed') return 'success';
  if (s === 'needs_clarification') return 'warning';
  return 'default';
}

export function ReviewStep({
  proposal,
  sourceSnapshot,
  suggestedFields,
  warnings = [],
  onBack,
  onApply,
  onSuggestedFieldChange,
  onToggleSuggestedFieldAccept,
  error,
  onDismissError,
  loading,
}: ReviewStepProps) {
  const fields = proposal.fields ?? [];
  const questions = proposal.questions ?? [];
  const snapById = useMemo(() => snapshotMap(sourceSnapshot), [sourceSnapshot]);
  const acceptedCount = suggestedFields.filter((s) => s.accepted).length;

  const introHint =
    suggestedFields.length > 0
      ? 'Проверьте и отредактируйте предложения ИИ: ключ/название/описание/тип каждого нового поля и значения для всех полей. Непринятые поля (✗) не будут созданы.'
      : 'Проверьте предложенные значения. Можно отредактировать текст single-полей, добавлять/удалять/редактировать элементы list-полей. Источники зафиксированы snapshot.';

  return (
    <div className="flex flex-col gap-3" data-review-step>
      <p className="text-sm text-text-muted">{introHint}</p>

      {suggestedFields.length > 0 && (
        <section
          className="flex flex-col gap-2 rounded border border-primary/30 bg-primary/5 p-3"
          data-suggested-section
        >
          <h4 className="text-sm font-semibold">
            Предложенные новые поля ({acceptedCount}/{suggestedFields.length})
          </h4>
          <div className="flex flex-col gap-2">
            {suggestedFields.map((sf, idx) => (
              <SuggestedFieldCard
                key={`${sf.originalKey}-${idx}`}
                sf={sf}
                index={idx}
                snapshotById={snapById}
                onChange={onSuggestedFieldChange}
                onToggleAccept={onToggleSuggestedFieldAccept}
              />
            ))}
          </div>
        </section>
      )}

      <div className="flex flex-col gap-2">
        {fields.length === 0 ? (
          <p className="px-2 py-3 text-center text-sm text-text-muted">
            Модель не вернула полей.
          </p>
        ) : (
          fields.map((f) => (
            <FieldCard
              key={f.field_key}
              field={f}
              snapshotById={snapById}
            />
          ))
        )}
      </div>

      {questions.length > 0 && (
        <section
          className="rounded border border-border bg-surface-2 p-3"
          data-questions-section
        >
          <h4 className="mb-2 text-sm font-semibold">Вопросы от модели</h4>
          <ul className="ml-4 list-disc text-sm">
            {questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </section>
      )}

      {warnings.length > 0 && (
        <section
          className="rounded border border-warning/30 bg-warning/5 p-3"
          data-warnings-section
        >
          <h4 className="mb-2 text-sm font-semibold text-warning">
            Предупреждения ({warnings.length})
          </h4>
          <ul className="ml-4 list-disc text-xs text-text-muted">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </section>
      )}

      {error && onDismissError && (
        <div
          className="flex items-start justify-between gap-3 rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"
          role="alert"
        >
          <div className="flex flex-col gap-1">
            <span>{error.text}</span>
            {error.code && (
              <span className="font-mono text-xs opacity-75">code: {error.code}</span>
            )}
          </div>
          <button
            type="button"
            onClick={onDismissError}
            className="rounded p-1 text-danger hover:bg-danger/20"
            aria-label="Закрыть ошибку"
          >
            ✕
          </button>
        </div>
      )}

      <div className="flex justify-between gap-2 pt-2">
        <Button variant="ghost" onClick={onBack} disabled={loading}>
          ← Назад
        </Button>
        <Button onClick={onApply} loading={loading} data-testid="apply-button">
          Применить
        </Button>
      </div>
    </div>
  );
}

function FieldCard({
  field,
  snapshotById,
}: {
  field: InitialProposalField;
  snapshotById: Map<string, DocumentSnapshot>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>('');

  const status = field.status;

  function startEdit() {
    if (field.mode === 'single' && field.single_value) {
      setDraft(field.single_value.text);
      setEditing(true);
    }
  }

  function cancel() {
    setEditing(false);
    setDraft('');
  }

  function save() {
    const next = draft.trim();
    if (!next) {
      cancel();
      return;
    }
    if (field.single_value) {
      field.single_value.text = next;
    }
    setEditing(false);
    setDraft('');
  }

  let body: ReactNode = null;
  if (status === 'proposed') {
    if (field.mode === 'single' && field.single_value) {
      body = editing ? (
          <textarea
            className="w-full rounded border border-border bg-bg p-2 text-sm"
            rows={4}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            data-testid={`field-edit-textarea-${field.field_key}`}
          />
      ) : (
        <div className="rounded border border-border bg-bg p-2 text-sm">
          <Markdown content={field.single_value.text} />
        </div>
      );
    } else if (field.mode === 'list' && field.list_value) {
      body = (
        <ul className="ml-4 list-disc text-sm">
          {field.list_value.items.map((it, i) => (
            <li key={i}>
              <Markdown content={it.text} />
              <SourcesInline
                refs={it.source_refs ?? []}
                snapshotById={snapshotById}
              />
            </li>
          ))}
        </ul>
      );
    } else {
      body = <p className="text-xs italic text-text-muted">пусто</p>;
    }
  } else if (status === 'needs_clarification') {
    body = (
      <p className="rounded border border-warning/30 bg-warning/5 p-2 text-sm text-warning">
        {field.clarification_question ?? 'Требуется уточнение'}
      </p>
    );
  } else {
    body = <p className="text-xs italic text-text-muted">Нет данных.</p>;
  }

  const sources =
    status === 'proposed' && field.mode === 'single' && field.single_value ? (
      <SourcesLine
        refs={field.single_value.source_refs ?? []}
        snapshotById={snapshotById}
      />
    ) : null;

  return (
    <div
      className="rounded border border-border bg-surface p-3"
      data-testid={`field-card-${field.field_key}`}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-text-muted">
          {field.field_key}
        </span>
        <span className="rounded bg-surface-2 px-2 py-0.5 text-xs">
          {field.mode}
        </span>
        <span
          className={clsx(
            'rounded px-2 py-0.5 text-xs',
            statusVariant(status) === 'success' &&
              'bg-success/10 text-success',
            statusVariant(status) === 'warning' &&
              'bg-warning/10 text-warning',
            statusVariant(status) === 'default' &&
              'bg-surface-2 text-text-muted',
          )}
        >
          {statusLabel(status)}
        </span>
      </div>
      <div>{body}</div>
      {sources}
      {status === 'proposed' && field.mode === 'single' && field.single_value && (
        <div className="mt-2 flex justify-end gap-2">
          {editing ? (
            <>
              <Button size="sm" variant="ghost" onClick={cancel}>
                Отменить
              </Button>
              <Button size="sm" onClick={save} data-testid={`field-save-${field.field_key}`}>
                Сохранить
              </Button>
            </>
          ) : (
            <Button size="sm" variant="ghost" onClick={startEdit}>
              Изменить
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function SuggestedFieldCard({
  sf,
  index,
  snapshotById,
  onChange,
  onToggleAccept,
}: {
  sf: SuggestedFieldUiState;
  index: number;
  snapshotById: Map<string, DocumentSnapshot>;
  onChange: (
    index: number,
    patch: Partial<SuggestedFieldUiState>,
  ) => void;
  onToggleAccept: (index: number) => void;
}) {
  const keyValid = FIELD_KEY_REGEX.test(sf.key);
  const [editingSingle, setEditingSingle] = useState(false);
  const [editingListIdx, setEditingListIdx] = useState<number | null>(null);
  const [draft, setDraft] = useState('');

  function startEditSingle() {
    if (sf.single_value) {
      setDraft(sf.single_value.text);
      setEditingSingle(true);
    }
  }

  function cancel() {
    setEditingSingle(false);
    setDraft('');
  }

  function saveSingle() {
    const next = draft.trim();
    if (!next) {
      cancel();
      return;
    }
    onChange(index, {
      single_value: {
        text: next,
        source_refs: sf.single_value?.source_refs ?? [],
      },
    });
    setEditingSingle(false);
    setDraft('');
  }

  function saveListItem() {
    if (editingListIdx === null || !sf.list_value) return;
    const next = draft.trim();
    if (!next) {
      setEditingListIdx(null);
      setDraft('');
      return;
    }
    const items = [...sf.list_value.items];
    items[editingListIdx] = {
      text: next,
      source_refs: items[editingListIdx]?.source_refs ?? [],
    };
    onChange(index, { list_value: { items } });
    setEditingListIdx(null);
    setDraft('');
  }

  let body: ReactNode = null;
  if (sf.initial_status === 'proposed') {
    if (sf.mode === 'single') {
      if (editingSingle) {
        body = (
          <textarea
            className="w-full rounded border border-border bg-bg p-2 text-sm"
            rows={4}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            data-suggested-edit-textarea={index}
          />
        );
      } else if (sf.single_value) {
        body = (
          <div className="rounded border border-border bg-bg p-2 text-sm">
            <Markdown content={sf.single_value.text} />
          </div>
        );
      }
    } else if (sf.list_value) {
      body = (
        <ul className="ml-4 list-disc text-sm">
          {sf.list_value.items.map((it, i) => (
            <li key={i}>
              {editingListIdx === i ? (
                <textarea
                  className="w-full rounded border border-border bg-bg p-2 text-sm"
                  rows={3}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  data-suggested-edit-list-textarea={`${index}-${i}`}
                  autoFocus
                />
              ) : (
                <button
                  type="button"
                  className="cursor-pointer text-left hover:underline"
                  onClick={() => {
                    setDraft(it.text);
                    setEditingListIdx(i);
                  }}
                  data-suggested-edit-list-item={`${index}-${i}`}
                >
                  <Markdown content={it.text} />
                </button>
              )}
              {editingListIdx !== i && (
                <SourcesInline
                  refs={it.source_refs ?? []}
                  snapshotById={snapshotById}
                />
              )}
            </li>
          ))}
        </ul>
      );
    }
  } else if (sf.initial_status === 'needs_clarification') {
    body = (
      <p className="rounded border border-warning/30 bg-warning/5 p-2 text-sm text-warning">
        {sf.clarification_question ?? 'Требуется уточнение'}
      </p>
    );
  } else {
    body = <p className="text-xs italic text-text-muted">Нет данных.</p>;
  }

  return (
    <div
      className={clsx(
        'rounded border p-3',
        sf.accepted
          ? 'border-border bg-surface'
          : 'border-border bg-surface-2 opacity-60',
      )}
      data-suggested-card={index}
      data-suggested-accepted={sf.accepted}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <input
          type="checkbox"
          checked={sf.accepted}
          onChange={() => onToggleAccept(index)}
          className="h-4 w-4"
          aria-label="Принять поле"
          data-testid={`suggested-accept-${index}`}
        />
        <input
          type="text"
          value={sf.key}
          pattern={FIELD_KEY_REGEX.source}
          onChange={(e) => onChange(index, { key: e.target.value })}
          className={
            'w-44 rounded border bg-bg px-2 py-1 font-mono text-xs ' +
            (keyValid ? 'border-border' : 'border-danger text-danger')
          }
          title="^[a-z][a-z0-9_]{0,63}$"
          data-suggested-key={index}
        />
        <span className="rounded bg-surface-2 px-2 py-0.5 text-xs">
          {sf.mode}
        </span>
        <span
          className={clsx(
            'rounded px-2 py-0.5 text-xs',
            statusVariant(sf.initial_status) === 'success' &&
              'bg-success/10 text-success',
            statusVariant(sf.initial_status) === 'warning' &&
              'bg-warning/10 text-warning',
            statusVariant(sf.initial_status) === 'default' &&
              'bg-surface-2 text-text-muted',
          )}
        >
          {statusLabel(sf.initial_status)}
        </span>
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-text-muted">Название:</span>
          <input
            type="text"
            value={sf.label}
            maxLength={256}
            onChange={(e) => onChange(index, { label: e.target.value })}
            className="rounded border border-border bg-bg px-2 py-1 text-sm"
            data-suggested-label={index}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-text-muted">Тип:</span>
          <div className="flex gap-2 text-sm">
            <label className="flex items-center gap-1">
              <input
                type="radio"
                name={`suggested-mode-${index}`}
                value="single"
                checked={sf.mode === 'single'}
                onChange={() => {
                  onChange(index, {
                    mode: 'single',
                    single_value:
                      sf.single_value ?? { text: '', source_refs: [] },
                    list_value: null,
                  });
                }}
                data-suggested-mode-single={index}
              />
              single
            </label>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                name={`suggested-mode-${index}`}
                value="list"
                checked={sf.mode === 'list'}
                onChange={() => {
                  onChange(index, {
                    mode: 'list',
                    list_value: sf.list_value ?? { items: [] },
                    single_value: null,
                  });
                }}
                data-suggested-mode-list={index}
              />
              list
            </label>
          </div>
        </label>
      </div>

      <label className="mt-2 flex flex-col gap-1 text-xs">
        <span className="text-text-muted">Описание:</span>
        <textarea
          rows={2}
          value={sf.description}
          placeholder="Подсказка для будущих LLM (опц.)"
          onChange={(e) => onChange(index, { description: e.target.value })}
          className="rounded border border-border bg-bg px-2 py-1 text-sm"
          data-suggested-description={index}
        />
      </label>

      <div className="mt-2">{body}</div>

      <div className="mt-2 flex flex-wrap justify-end gap-2">
        {sf.initial_status === 'proposed' && sf.mode === 'single' && (
          <>
            {editingSingle ? (
              <>
                <Button size="sm" variant="ghost" onClick={cancel}>
                  Отменить
                </Button>
                <Button
                  size="sm"
                  onClick={saveSingle}
                  data-suggested-save-single={index}
                >
                  Сохранить
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={startEditSingle}
                data-suggested-edit-single={index}
              >
                Изменить
              </Button>
            )}
          </>
        )}
        {sf.initial_status === 'proposed' && sf.mode === 'list' && (
          <>
            {editingListIdx !== null ? (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setEditingListIdx(null);
                    setDraft('');
                  }}
                >
                  Отменить
                </Button>
                <Button
                  size="sm"
                  onClick={saveListItem}
                  data-suggested-save-list-item={index}
                >
                  Сохранить
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  const items = sf.list_value?.items ?? [];
                  onChange(index, {
                    list_value: {
                      items: [...items, { text: '', source_refs: [] }],
                    },
                  });
                }}
                data-suggested-add-list-item={index}
              >
                + Элемент
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SourcesLine({
  refs,
  snapshotById,
}: {
  refs: string[];
  snapshotById: Map<string, DocumentSnapshot>;
}) {
  if (!refs || refs.length === 0) return null;
  const labels = refs.map((r) => refLabel(r, snapshotById)).filter(Boolean);
  if (labels.length === 0) return null;
  return (
    <div className="mt-1 text-xs text-text-muted" data-source-line>
      <span className="mr-1">Источник:</span>
      {labels.map((l, i) => (
        <span key={i}>
          {i > 0 && '; '}
          <span className="font-mono" title={refs[i]}>
            {l}
          </span>
        </span>
      ))}
    </div>
  );
}

function SourcesInline({
  refs,
  snapshotById,
}: {
  refs: string[];
  snapshotById: Map<string, DocumentSnapshot>;
}) {
  if (!refs || refs.length === 0) return null;
  const labels = refs.map((r) => refLabel(r, snapshotById)).filter(Boolean);
  if (labels.length === 0) return null;
  return (
    <span className="ml-1 text-xs text-text-muted" data-source-inline>
      {labels.map((l, i) => (
        <span key={i}>
          {i > 0 && '; '}
          <span className="font-mono" title={refs[i]}>
            {l}
          </span>
        </span>
      ))}
    </span>
  );
}
