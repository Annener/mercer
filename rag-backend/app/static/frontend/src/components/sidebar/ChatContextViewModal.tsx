import { useQuery } from '@tanstack/react-query';
import { Modal } from '@/components/ui';
import { api } from '@/api/client';
import type { ChatMetadata, UUID } from '@/api/types';

interface ChatContextViewModalProps {
  chatId: UUID | null;
  onClose: () => void;
}

type DriftHint = NonNullable<
  NonNullable<ChatMetadata['scene_state']>['drift']
> extends { _hints?: Array<infer H> }
  ? H
  : never;

export function ChatContextViewModal({ chatId, onClose }: ChatContextViewModalProps) {
  const open = chatId !== null;

  const chatQuery = useQuery({
    queryKey: ['chat', chatId],
    queryFn: () => api.getChat(chatId!),
    enabled: !!chatId,
    staleTime: 5_000,
  });

  const chat = chatQuery.data?.chat;
  const sceneState = chat?.metadata?.scene_state;

  const title = chat?.title ? `Контекст чата: ${chat.title}` : 'Контекст чата';

  return (
    <Modal open={open} onClose={onClose} title={title} size="lg">
      <div className="p-4">
        {chatQuery.isLoading && (
          <div className="flex items-center gap-2 text-sm text-text-muted">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            Загрузка контекста…
          </div>
        )}
        {chatQuery.error && (
          <div className="space-y-2 text-sm text-danger">
            <p>Не удалось загрузить контекст чата.</p>
            <button
              type="button"
              onClick={() => {
                void chatQuery.refetch();
              }}
              className="rounded border border-border bg-surface px-2 py-1 text-xs text-text hover:bg-surface-2"
            >
              Повторить
            </button>
          </div>
        )}
        {chat && !chatQuery.isLoading && (
          <div className="space-y-5">
            <p className="text-xs text-text-muted">
              Это контекст, который drift-модель собирает по ходу чата: активная сцена
              (от LLM через <code className="font-mono">update_scene_state</code>) и
              найденные расхождения с Campaign State (drift hints). Только просмотр.
            </p>
            <ActiveSceneBlock sceneState={sceneState} />
            <DriftHintsBlock sceneState={sceneState} />
          </div>
        )}
      </div>
    </Modal>
  );
}

function ActiveSceneBlock({
  sceneState,
}: {
  sceneState: ChatMetadata['scene_state'];
}) {
  const explicit = sceneState?.explicit;
  const hasExplicit =
    explicit !== undefined && explicit !== null && Object.keys(explicit).length > 0;

  return (
    <section>
      <header className="mb-2">
        <h4 className="text-sm font-semibold text-text">Активная сцена</h4>
        <p className="mt-0.5 text-xs text-text-muted">
          Заполняется большой LLM через инструмент{' '}
          <code className="font-mono">update_scene_state</code> (локация, активные NPC,
          текущий акт и т.п.).
        </p>
      </header>
      {!hasExplicit ? (
        <div className="rounded border border-dashed border-border bg-surface-2/40 p-3 text-sm italic text-text-muted">
          Модель ещё не записывала активную сцену для этого чата.
        </div>
      ) : (
        <div className="rounded border border-border bg-surface-2/40 p-3">
          <SceneStateTable data={explicit!} />
        </div>
      )}
    </section>
  );
}

function DriftHintsBlock({
  sceneState,
}: {
  sceneState: ChatMetadata['scene_state'];
}) {
  const hints = sceneState?.drift?._hints ?? [];
  const ts = sceneState?.drift?._ts;

  return (
    <section>
      <header className="mb-2 flex items-center justify-between">
        <div>
          <h4 className="text-sm font-semibold text-text">
            Дрейф контекста (drift hints)
          </h4>
          <p className="mt-0.5 text-xs text-text-muted">
            Подсказки от локальной drift-модели о расхождениях последних сообщений
            с текущим Campaign State. Работает автоматически в фоне.
          </p>
        </div>
        {ts && (
          <span className="shrink-0 text-[10px] text-text-muted">
            обновлено: {new Date(ts).toLocaleString('ru-RU')}
          </span>
        )}
      </header>
      {hints.length === 0 ? (
        <div className="rounded border border-dashed border-border bg-surface-2/40 p-3 text-sm italic text-text-muted">
          Drift-детектор ещё не нашёл расхождений или они не прошли порог confidence.
        </div>
      ) : (
        <ul className="space-y-2">
          {hints.map((hint, idx) => (
            <DriftHintRow key={idx} hint={hint} />
          ))}
        </ul>
      )}
    </section>
  );
}

function DriftHintRow({
  hint,
}: {
  hint: DriftHint;
}) {
  const conf = typeof hint.confidence === 'number' ? hint.confidence : null;
  const confLabel = conf !== null ? conf.toFixed(2) : '?';
  const confClass =
    conf === null
      ? 'bg-surface-2 text-text-muted'
      : conf >= 0.75
        ? 'bg-success/15 text-success'
        : conf >= 0.5
          ? 'bg-warning/15 text-warning'
          : 'bg-surface-2 text-text-muted';

  const fieldRef = hint.adds_field ?? hint.contradicts_field;
  const fieldKind = hint.adds_field ? 'adds' : hint.contradicts_field ? 'contradicts' : null;

  return (
    <li className="rounded border border-border bg-surface-2/40 p-3">
      <div className="flex items-start gap-2">
        <span
          className={`inline-flex shrink-0 items-center rounded px-1.5 py-0.5 font-mono text-[10px] font-medium ${confClass}`}
          title="Confidence drift-модели (0..1)"
        >
          conf={confLabel}
        </span>
        <div className="flex-1 space-y-1">
          {hint.fact && (
            <p className="text-sm text-text">{hint.fact}</p>
          )}
          {fieldRef && (
            <p className="text-xs text-text-muted">
              <span className="font-medium">
                {fieldKind === 'adds'
                  ? 'новое поле:'
                  : fieldKind === 'contradicts'
                    ? 'противоречит полю:'
                    : 'поле:'}
              </span>{' '}
              <code className="font-mono">{fieldRef}</code>
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

function SceneStateTable({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);

  return (
    <dl className="divide-y divide-border text-sm">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[180px_1fr] gap-3 py-2">
          <dt className="break-words font-mono text-xs text-text-muted">{key}</dt>
          <dd className="break-words text-text">
            <SceneStateValue value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function SceneStateValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="italic text-text-muted">— пусто —</span>;
  }
  if (typeof value === 'string') {
    return <span className="whitespace-pre-wrap">{value}</span>;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return <span className="font-mono">{String(value)}</span>;
  }
  try {
    return (
      <pre className="overflow-x-auto rounded bg-surface px-2 py-1 font-mono text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  } catch {
    return <span className="italic text-text-muted">(не сериализуется)</span>;
  }
}
