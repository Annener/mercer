import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { HttpError, api } from '@/api/client';
import type { PlatformSetting, SidecarStatus } from '@/api/types';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmModal,
  Field,
  Input,
  Modal,
} from '@/components/ui';
import { clsx } from '@/components/ui/clsx';

const PARAMS_EXCLUDED_KEYS = new Set<string>([
  'watchdog_auto_index_extensions',
  'watchdog.interval_sec',
]);

interface ParamGroup {
  id: string;
  title: string;
  keys: string[];
  description?: string;
}

const PARAM_GROUPS: ParamGroup[] = [
  {
    id: 'chat',
    title: 'Настройки чатов',
    keys: ['chat.auto_title', 'chat.stream_answers', 'chat.max_clarification_turns'],
  },
  {
    id: 'rag',
    title: 'Настройки взаимодействия с RAG',
    keys: ['retrieval.enabled', 'retrieval.top_k'],
  },
  {
    id: 'indexing',
    title: 'Настройки индексации',
    keys: [
      'pdf_sidecar.fallback_to_pdfminer',
      'chunking.chunk_size',
      'chunking.entity_aware_mode',
      'chunking.overlap',
      'pdf_sidecar.timeout_seconds',
      'pdf_sidecar.url',
    ],
  },
  {
    id: 'drift',
    title: 'Drift loop (фоновое обновление контекста)',
    keys: ['drift.enabled', 'drift.detect_enabled', 'drift.draft_enabled'],
    description:
      'Локальная модель (QVikhr) анализирует последние сообщения чата и Campaign State. ' +
      'При расхождениях формируется draft, который появляется в чате как «Возможные обновления». ' +
      'Отключение останавливает фоновый анализ — карточка предложений перестанет появляться. ' +
      'Сама модель при этом остаётся активной и доступной в её собственных настройках.',
  },
];

const WATCHDOG_KNOWN_EXTENSIONS = ['.md', '.pdf', '.docx', '.txt', '.rst', '.html'];

export function ParamsTab() {
  const queryClient = useQueryClient();
  const paramsQuery = useQuery({
    queryKey: ['settings', 'params'],
    queryFn: () => api.getSettingsParams(),
  });

  const [draft, setDraft] = useState<Record<string, string | number | boolean>>({});
  const [original, setOriginal] = useState<Record<string, string | number | boolean>>({});
  const [resetOpen, setResetOpen] = useState(false);

  useEffect(() => {
    if (!paramsQuery.data) return;
    const next: Record<string, string | number | boolean> = {};
    for (const p of paramsQuery.data) {
      next[p.key] = p.value;
    }
    setDraft(next);
    setOriginal(next);
  }, [paramsQuery.data]);

  const grouped = useMemo(() => buildGroups(paramsQuery.data ?? []), [paramsQuery.data]);

  const dirtyKeys = useMemo(() => {
    const keys: string[] = [];
    for (const k of Object.keys(draft)) {
      if (draft[k] !== original[k]) keys.push(k);
    }
    return keys;
  }, [draft, original]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      for (const key of dirtyKeys) {
        await api.updateSettingsParam(key, draft[key]);
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'params'] });
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => api.resetSettingsParams(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'params'] });
      setResetOpen(false);
    },
  });

  if (paramsQuery.isLoading) {
    return <p className="text-sm text-text-muted">Загрузка…</p>;
  }
  if (paramsQuery.error) {
    return (
      <p className="text-sm text-danger">
        Не удалось загрузить параметры: {String(paramsQuery.error)}
      </p>
    );
  }

  const isDirty = dirtyKeys.length > 0;

  return (
    <div className="space-y-6">
      {grouped.groups.map((group) => (
        <ParamGroupCard
          key={group.id}
          title={group.title}
          description={group.description}
          params={group.params}
          draft={draft}
          onChange={(key, value) => setDraft((d) => ({ ...d, [key]: value }))}
        />
      ))}

      {grouped.ungrouped.length > 0 && (
        <ParamGroupCard
          title="Прочие параметры"
          params={grouped.ungrouped}
          draft={draft}
          onChange={(key, value) => setDraft((d) => ({ ...d, [key]: value }))}
        />
      )}

      <WatchdogCard />

      <SidecarCard />

      <div className="flex items-center justify-end gap-2 border-t border-border pt-4">
        {saveMutation.error && (
          <span className="mr-auto text-sm text-danger">
            Ошибка сохранения:{' '}
            {saveMutation.error instanceof HttpError
              ? saveMutation.error.message
              : String(saveMutation.error)}
          </span>
        )}
        {saveMutation.isSuccess && !isDirty && (
          <span className="mr-auto text-sm text-success">Сохранено</span>
        )}
        <Button
          variant="ghost"
          onClick={() => setResetOpen(true)}
          disabled={resetMutation.isPending}
        >
          Сбросить к умолчаниям
        </Button>
        <Button
          onClick={() => saveMutation.mutate()}
          disabled={!isDirty}
          loading={saveMutation.isPending}
        >
          Сохранить
        </Button>
      </div>

      <ConfirmModal
        open={resetOpen}
        title="Сброс параметров"
        message="Сбросить все параметры платформы к значениям по умолчанию?"
        confirmLabel="Сбросить"
        variant="danger"
        pending={resetMutation.isPending}
        error={
          resetMutation.error
            ? resetMutation.error instanceof HttpError
              ? resetMutation.error.message
              : String(resetMutation.error)
            : null
        }
        onConfirm={() => resetMutation.mutate()}
        onClose={() => setResetOpen(false)}
      />
    </div>
  );
}

function buildGroups(params: PlatformSetting[]): {
  groups: Array<{
    id: string;
    title: string;
    description?: string;
    params: PlatformSetting[];
  }>;
  ungrouped: PlatformSetting[];
} {
  const byKey = new Map<string, PlatformSetting>();
  for (const p of params) {
    if (PARAMS_EXCLUDED_KEYS.has(p.key)) continue;
    byKey.set(p.key, p);
  }

  const groups: Array<{
    id: string;
    title: string;
    description?: string;
    params: PlatformSetting[];
  }> = [];
  const usedKeys = new Set<string>();

  for (const g of PARAM_GROUPS) {
    const items: PlatformSetting[] = [];
    for (const key of g.keys) {
      const p = byKey.get(key);
      if (p) {
        items.push(p);
        usedKeys.add(key);
      }
    }
    if (items.length > 0) {
      groups.push({
        id: g.id,
        title: g.title,
        description: g.description,
        params: items,
      });
    }
  }

  const ungrouped = [...byKey.values()]
    .filter((p) => !usedKeys.has(p.key))
    .sort((a, b) => a.key.localeCompare(b.key));

  return { groups, ungrouped };
}

interface ParamGroupCardProps {
  title: string;
  description?: string;
  params: PlatformSetting[];
  draft: Record<string, string | number | boolean>;
  onChange: (key: string, value: string | number | boolean) => void;
}

function ParamGroupCard({ title, description, params, draft, onChange }: ParamGroupCardProps) {
  return (
    <Card title={title}>
      {description && (
        <p className="mb-3 text-xs leading-relaxed text-text-muted">{description}</p>
      )}
      <div className="max-w-[640px] space-y-3">
        {params.map((p) => (
          <ParamRow
            key={p.key}
            param={p}
            value={draft[p.key] ?? p.value}
            onChange={(value) => onChange(p.key, value)}
          />
        ))}
      </div>
    </Card>
  );
}

interface ParamRowProps {
  param: PlatformSetting;
  value: string | number | boolean;
  onChange: (value: string | number | boolean) => void;
}

function ParamRow({ param, value, onChange }: ParamRowProps) {
  const id = `param-${param.key.replace(/\./g, '-')}`;
  const hint = param.hint?.trim();

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="block text-sm font-medium text-text">
          {param.label || param.key}
        </label>
        {hint && (
          <span
            tabIndex={0}
            aria-label={hint}
            title={hint}
            className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-surface-2 text-xs text-text-muted"
          >
            ?
          </span>
        )}
      </div>
      <ParamControl
        id={id}
        param={param}
        value={value}
        onChange={onChange}
      />
      {hint && <p className="text-xs text-text-muted">{hint}</p>}
    </div>
  );
}

function ParamControl({
  id,
  param,
  value,
  onChange,
}: {
  id: string;
  param: PlatformSetting;
  value: string | number | boolean;
  onChange: (value: string | number | boolean) => void;
}) {
  if (param.value_type === 'bool') {
    return (
      <Checkbox
        id={id}
        checked={value === true}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  }

  if (param.value_type === 'int') {
    return (
      <Input
        id={id}
        type="number"
        value={typeof value === 'number' ? value : Number(value) || 0}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
      />
    );
  }

  if (param.value_type === 'float') {
    return (
      <Input
        id={id}
        type="number"
        step="any"
        value={typeof value === 'number' ? value : Number(value) || 0}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
      />
    );
  }

  return (
    <Input
      id={id}
      type="text"
      value={typeof value === 'string' ? value : String(value ?? '')}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function WatchdogCard() {
  const queryClient = useQueryClient();
  const watchdogQuery = useQuery({
    queryKey: ['watchdog'],
    queryFn: () => api.getWatchdogSettings(),
  });

  const initialExtensions = useMemo(() => {
    const v = watchdogQuery.data?.auto_index_extensions ?? [];
    return Array.isArray(v) ? v : [];
  }, [watchdogQuery.data]);

  const [exts, setExts] = useState<string[]>(initialExtensions);
  const [interval, setInterval] = useState<number>(watchdogQuery.data?.interval_sec ?? 60);
  const [customExt, setCustomExt] = useState('');
  const [msg, setMsg] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  useEffect(() => {
    setExts(initialExtensions);
    setInterval(watchdogQuery.data?.interval_sec ?? 60);
  }, [initialExtensions, watchdogQuery.data?.interval_sec]);

  const saveMutation = useMutation({
    mutationFn: () => api.saveWatchdogSettings(exts, interval),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['watchdog'] });
      setMsg({ kind: 'ok', text: 'Настройки watchdog сохранены' });
    },
    onError: (err) => {
      setMsg({
        kind: 'error',
        text: err instanceof HttpError ? err.message : 'Не удалось сохранить',
      });
    },
  });

  const allExts = useMemo(() => {
    const set = new Set<string>([...WATCHDOG_KNOWN_EXTENSIONS, ...exts]);
    return [...set].sort();
  }, [exts]);

  const enabledExts = new Set(exts);

  const addCustomExt = () => {
    const value = customExt.trim();
    if (!value) return;
    const normalised = value.startsWith('.') ? value : `.${value}`;
    if (exts.includes(normalised)) {
      setCustomExt('');
      return;
    }
    setExts([...exts, normalised]);
    setCustomExt('');
  };

  const removeExt = (ext: string) => {
    setExts(exts.filter((e) => e !== ext));
  };

  if (watchdogQuery.isLoading) {
    return (
      <Card title="Vault Watchdog">
        <p className="text-sm text-text-muted">Загрузка…</p>
      </Card>
    );
  }

  return (
    <Card
      title="Vault Watchdog"
      actions={
        <Button onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
          Сохранить
        </Button>
      }
    >
      <div className="max-w-[640px] space-y-4">
        <Field label="Интервал сканирования (сек)" hint="Минимум 10 секунд. Применяется на следующем цикле без перезапуска.">
          <Input
            type="number"
            min={10}
            step={1}
            value={interval}
            onChange={(e) => setInterval(Math.max(10, Number(e.target.value) || 0))}
          />
        </Field>

        <div>
          <p className="mb-1 block text-sm font-medium text-text">Отслеживаемые расширения</p>
          <p className="mb-2 text-xs text-text-muted">
            Файлы с этими расширениями будут автоматически индексироваться при добавлении в хранилище.
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {allExts.map((ext) => (
              <label
                key={ext}
                className="flex items-center justify-between gap-2 rounded border border-border px-2 py-1.5 text-sm"
              >
                <Checkbox
                  checked={enabledExts.has(ext)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setExts([...exts, ext]);
                    } else {
                      removeExt(ext);
                    }
                  }}
                  label={ext}
                />
              </label>
            ))}
          </div>

          <div className="mt-3 flex gap-2">
            <Input
              value={customExt}
              onChange={(e) => setCustomExt(e.target.value)}
              placeholder=".ext"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addCustomExt();
                }
              }}
            />
            <Button variant="secondary" onClick={addCustomExt}>
              Добавить
            </Button>
          </div>
        </div>

        {msg && (
          <p
            className={clsx(
              'min-h-[1.2em] text-sm',
              msg.kind === 'ok' ? 'text-success' : 'text-danger',
            )}
          >
            {msg.text}
          </p>
        )}
      </div>
    </Card>
  );
}

function SidecarCard() {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({
    queryKey: ['sidecar', 'status'],
    queryFn: () => api.getSidecarStatus(),
    refetchInterval: 5000,
  });

  const [actionMsg, setActionMsg] = useState<{ kind: 'loading' | 'ok' | 'error'; text: string } | null>(
    null,
  );
  const [installOpen, setInstallOpen] = useState(false);

  const start = useMutation({
    mutationFn: () => api.sidecarStart(),
    onMutate: () => setActionMsg({ kind: 'loading', text: 'Выполняется...' }),
    onSuccess: (res) => {
      const message =
        (res && typeof res === 'object' && 'message' in res
          ? String((res as { message?: unknown }).message ?? '')
          : '') || 'Готово';
      setActionMsg({ kind: 'ok', text: message });
      void queryClient.invalidateQueries({ queryKey: ['sidecar', 'status'] });
    },
    onError: (err) => {
      setActionMsg({
        kind: 'error',
        text: `Ошибка: ${err instanceof HttpError ? err.message : String(err)}`,
      });
    },
  });
  const stop = useMutation({
    mutationFn: () => api.sidecarStop(),
    onMutate: () => setActionMsg({ kind: 'loading', text: 'Выполняется...' }),
    onSuccess: (res) => {
      const message =
        (res && typeof res === 'object' && 'message' in res
          ? String((res as { message?: unknown }).message ?? '')
          : '') || 'Готово';
      setActionMsg({ kind: 'ok', text: message });
      void queryClient.invalidateQueries({ queryKey: ['sidecar', 'status'] });
    },
    onError: (err) => {
      setActionMsg({
        kind: 'error',
        text: `Ошибка: ${err instanceof HttpError ? err.message : String(err)}`,
      });
    },
  });
  const restart = useMutation({
    mutationFn: () => api.sidecarRestart(),
    onMutate: () => setActionMsg({ kind: 'loading', text: 'Выполняется...' }),
    onSuccess: (res) => {
      const message =
        (res && typeof res === 'object' && 'message' in res
          ? String((res as { message?: unknown }).message ?? '')
          : '') || 'Готово';
      setActionMsg({ kind: 'ok', text: message });
      void queryClient.invalidateQueries({ queryKey: ['sidecar', 'status'] });
    },
    onError: (err) => {
      setActionMsg({
        kind: 'error',
        text: `Ошибка: ${err instanceof HttpError ? err.message : String(err)}`,
      });
    },
  });

  const status: SidecarStatus | undefined = statusQuery.data;
  const canControl = !!status && !status.agent_unavailable && status.installed;

  return (
    <Card title="PDF Sidecar">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-text-muted">Статус:</span>
          <SidecarStatusBadge status={status} />
          {status?.running && status.pid != null && (
            <span className="text-xs text-text-muted">PID {status.pid}</span>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={!canControl || status?.running || start.isPending}
            loading={start.isPending}
            onClick={() => start.mutate()}
          >
            Запустить
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!canControl || !status?.running || stop.isPending}
            loading={stop.isPending}
            onClick={() => stop.mutate()}
          >
            Остановить
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!canControl || !status?.running || restart.isPending}
            loading={restart.isPending}
            onClick={() => restart.mutate()}
          >
            Перезапустить
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={status?.agent_unavailable}
            onClick={() => {
              setInstallOpen(true);
            }}
          >
            Установить / Переустановить
          </Button>
        </div>

        {actionMsg && (
          <p
            className={clsx(
              'min-h-[1.2em] text-sm',
              actionMsg.kind === 'loading' && 'text-text-muted',
              actionMsg.kind === 'ok' && 'text-success',
              actionMsg.kind === 'error' && 'text-danger',
            )}
          >
            {actionMsg.text}
          </p>
        )}
      </div>

      <SidecarInstallModal
        open={installOpen}
        onClose={() => setInstallOpen(false)}
        onCompleted={() => {
          void queryClient.invalidateQueries({ queryKey: ['sidecar', 'status'] });
        }}
      />
    </Card>
  );
}

function SidecarStatusBadge({ status }: { status?: SidecarStatus }) {
  if (!status) {
    return <Badge>загрузка…</Badge>;
  }
  if (status.agent_unavailable) {
    return <Badge variant="danger">agent недоступен</Badge>;
  }
  if (!status.installed) {
    return <Badge variant="warning">не установлен</Badge>;
  }
  if (status.running) {
    return <Badge variant="success">запущен</Badge>;
  }
  return <Badge>остановлен</Badge>;
}

interface SidecarInstallModalProps {
  open: boolean;
  onClose: () => void;
  onCompleted: () => void;
}

function SidecarInstallModal({ open, onClose, onCompleted }: SidecarInstallModalProps) {
  const [output, setOutput] = useState('');
  const [title, setTitle] = useState('Установка PDF Sidecar');
  const [done, setDone] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!open) return;
    setOutput('');
    setTitle('Установка PDF Sidecar');
    setDone(false);

    const url = api.getSidecarInstallStreamUrl();
    const es = new EventSource(url);
    sourceRef.current = es;

    es.onmessage = (ev) => {
      const line = ev.data;
      setOutput((prev) => prev + line + '\n');
      if (line.startsWith('[DONE]')) {
        es.close();
        sourceRef.current = null;
        setTitle('Установка завершена');
        setDone(true);
        onCompleted();
      }
    };
    es.onerror = () => {
      setOutput((prev) => prev + '\n[Соединение прервано]\n');
      es.close();
      sourceRef.current = null;
    };

    return () => {
      es.close();
      sourceRef.current = null;
    };
  }, [open, onCompleted]);

  const close = () => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
    onClose();
  };

  return (
    <Modal open={open} onClose={close} title={title} size="lg">
      <div className="p-4">
        <pre className="max-h-[60vh] min-h-[200px] overflow-auto rounded bg-surface-2 p-3 font-mono text-xs text-text">
          {output || (done ? '' : 'Подключение…')}
        </pre>
        <div className="mt-3 flex justify-end">
          <Button onClick={close}>{done ? 'Готово' : 'Закрыть'}</Button>
        </div>
      </div>
    </Modal>
  );
}