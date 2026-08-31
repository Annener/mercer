import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Checkbox,
  ConfirmModal,
  EmptyState,
  Field,
  Input,
  Modal,
  Select,
  SelectWrapper,
  SettingsCard,
  StatusBadge,
  type SettingsCardMenuItem,
} from '@/components/ui';
import { api, HttpError } from '@/api/client';
import type {
  CreateDriftModelRequest,
  CreateEmbeddingModelRequest,
  CreateGenerationModelRequest,
  CreateRerankModelRequest,
  DriftModel,
  EmbeddingModel,
  GenerationModel,
  ModelCheckResult,
  ModelKind,
  RerankModel,
  UpdateDriftModelRequest,
  UpdateEmbeddingModelRequest,
  UpdateGenerationModelRequest,
  UpdateRerankModelRequest,
  Vault,
} from '@/api/types';

type ModelKindOption = 'generation' | 'embedding' | 'rerank' | 'drift';

const MODEL_KIND_OPTIONS: Array<{ value: ModelKindOption; label: string }> = [
  { value: 'generation', label: 'Генеративная модель' },
  { value: 'embedding', label: 'Embedding-модель' },
  { value: 'rerank', label: 'Rerank-модель' },
  { value: 'drift', label: 'Drift-модель' },
];

const EMBEDDING_PROVIDERS: Array<{ value: string; label: string }> = [
  { value: 'openai_compatible', label: 'OpenAI compatible' },
  { value: 'ollama', label: 'Ollama' },
  { value: 'sidecar', label: 'PDF Sidecar' },
];

const RERANK_PROVIDERS: Array<{ value: string; label: string }> = [
  { value: 'openai_compatible', label: 'OpenAI compatible' },
  { value: 'cohere', label: 'Cohere' },
  { value: 'jina', label: 'Jina' },
  { value: 'ollama', label: 'Ollama' },
];

const DRIFT_PROVIDERS: Array<{ value: string; label: string }> = [
  { value: 'host_sidecar', label: 'PDF Sidecar (локальная)' },
  { value: 'openai_compatible', label: 'OpenAI compatible' },
];

const DEFAULT_DRIFT_SIDECAR_URL = 'http://host.docker.internal:8765';

export function ModelsTab() {
  const [kindToChoose, setKindToChoose] = useState(false);
  const [pendingKind, setPendingKind] = useState<ModelKindOption | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Button onClick={() => setKindToChoose(true)}>+ Добавить</Button>
      </div>

      <ChooseModelKindModal
        open={kindToChoose}
        onSelect={(kind) => {
          setKindToChoose(false);
          setPendingKind(kind);
        }}
        onClose={() => setKindToChoose(false)}
      />

      {pendingKind === 'generation' && (
        <CreateGenerationModelInline
          onCreated={() => setPendingKind(null)}
          onClose={() => setPendingKind(null)}
        />
      )}
      {pendingKind === 'embedding' && (
        <CreateEmbeddingModelInline
          onCreated={() => setPendingKind(null)}
          onClose={() => setPendingKind(null)}
        />
      )}
      {pendingKind === 'rerank' && (
        <CreateRerankModelInline
          onCreated={() => setPendingKind(null)}
          onClose={() => setPendingKind(null)}
        />
      )}
      {pendingKind === 'drift' && (
        <CreateDriftModelInline
          onCreated={() => setPendingKind(null)}
          onClose={() => setPendingKind(null)}
        />
      )}

      <ModelSection title="Генеративные модели">
        <GenerationModelsBody />
      </ModelSection>

      <ModelSection title="Embedding-модели">
        <EmbeddingModelsBody />
      </ModelSection>

      <ModelSection title="Rerank-модели">
        <RerankModelsBody />
      </ModelSection>

      <ModelSection title="Drift-модели">
        <DriftModelsBody />
      </ModelSection>
    </div>
  );
}

function ModelSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <header className="mb-3">
        <h3 className="text-lg font-semibold">{title}</h3>
      </header>
      {children}
    </section>
  );
}

interface ChooseModelKindModalProps {
  open: boolean;
  onSelect: (kind: ModelKindOption) => void;
  onClose: () => void;
}

function ChooseModelKindModal({ open, onSelect, onClose }: ChooseModelKindModalProps) {
  const [kind, setKind] = useState<ModelKindOption | ''>('');
  return (
    <Modal open={open} onClose={onClose} title="Выберите тип модели" size="sm">
      <div className="space-y-3 p-4">
        <SelectWrapper label="Тип модели">
          <Select
            value={kind}
            onChange={(e) => setKind(e.target.value as ModelKindOption)}
            options={MODEL_KIND_OPTIONS}
            placeholder="— выберите тип —"
          />
        </SelectWrapper>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button
            disabled={!kind}
            onClick={() => {
              if (kind) onSelect(kind);
            }}
          >
            Продолжить →
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function ModelStatusBadge({ isActive, isEnabled }: { isActive: boolean; isEnabled: boolean }) {
  if (isActive) return <StatusBadge kind="active" />;
  if (!isEnabled) return <StatusBadge kind="disabled" />;
  return <StatusBadge kind="ready" />;
}

function GenerationModelsBody() {
  const queryClient = useQueryClient();
  const modelsQuery = useQuery({
    queryKey: ['models', 'generation'],
    queryFn: () => api.getGenerationModels(),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['models', 'generation'] });
    void queryClient.invalidateQueries({ queryKey: ['model-health'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
  };

  if (modelsQuery.isLoading) {
    return <p className="text-sm text-text-muted">Загрузка…</p>;
  }
  const models = modelsQuery.data ?? [];
  if (models.length === 0) {
    return (
      <EmptyState
        title="Нет генеративных моделей"
        description="Создайте первую модель через кнопку «Добавить» сверху"
      />
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
      {models.map((m) => (
        <GenerationModelCard key={m.model_id} model={m} onChanged={invalidate} />
      ))}
    </div>
  );
}

interface GenerationModelCardProps {
  model: GenerationModel;
  onChanged: () => void;
}

function GenerationModelCard({ model, onChanged }: GenerationModelCardProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [checkResult, setCheckResult] = useState<ModelCheckResult | null>(null);

  const isActive = !!model.is_active;
  const isEnabled = model.enabled !== false;

  const activateMutation = useMutation({
    mutationFn: () => api.setActiveGenerationModel(model.model_id),
    onSuccess: onChanged,
  });
  const deactivateMutation = useMutation({
    mutationFn: () => api.deactivateGenerationModel(model.model_id),
    onSuccess: onChanged,
  });
  const checkMutation = useMutation({
    mutationFn: () => api.checkGenerationModel(model.model_id),
    onSuccess: (res) => setCheckResult(res),
    onError: (err) =>
      setCheckResult({
        ok: false,
        error: err instanceof HttpError ? err.message : 'Не удалось выполнить проверку',
      }),
  });

  const badges = <ModelStatusBadge isActive={isActive} isEnabled={isEnabled} />;

  const menu: SettingsCardMenuItem[] = [
    { key: 'edit', label: 'Изменить', onClick: () => setEditOpen(true) },
    {
      key: 'check',
      label: checkMutation.isPending ? 'Проверка…' : 'Проверить',
      disabled: checkMutation.isPending,
      onClick: () => {
        setCheckResult(null);
        checkMutation.mutate();
      },
    },
  ];
  if (isActive) {
    menu.push({
      key: 'deactivate',
      label: 'Деактивировать',
      onClick: () => deactivateMutation.mutate(),
    });
  } else {
    menu.push({
      key: 'activate',
      label: 'Активировать',
      onClick: () => activateMutation.mutate(),
    });
  }
  menu.push({
    key: 'delete',
    label: 'Удалить',
    danger: true,
    disabled: isActive,
    onClick: () => setDeleteOpen(true),
  });

  return (
    <>
      <SettingsCard
        title={model.display_name ?? model.model_id}
        badges={badges}
        subtitle={model.provider}
        active={isActive}
        menu={menu}
      />

      <EditGenerationModelModal
        open={editOpen}
        model={model}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          setEditOpen(false);
          onChanged();
        }}
      />

      <DeleteModelModal
        open={deleteOpen}
        title="Удалить генеративную модель"
        name={model.display_name ?? model.model_id}
        onClose={() => setDeleteOpen(false)}
        onConfirm={() => api.deleteGenerationModel(model.model_id)}
        onDeleted={onChanged}
      />

      <CheckResultModal
        open={!!checkResult || checkMutation.isPending}
        pending={checkMutation.isPending}
        result={checkResult}
        onClose={() => setCheckResult(null)}
        title={`Проверка модели «${model.display_name ?? model.model_id}»`}
      />
    </>
  );
}

interface EditGenerationModelModalProps {
  open: boolean;
  model: GenerationModel;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

function EditGenerationModelModal({ open, model, onClose, onSaved }: EditGenerationModelModalProps) {
  const [displayName, setDisplayName] = useState(model.display_name ?? '');
  const [provider, setProvider] = useState(model.provider ?? 'openai_compatible');
  const [baseUrl, setBaseUrl] = useState(model.base_url ?? '');
  const [apiKey, setApiKey] = useState('');
  const [timeout, setTimeout] = useState(model.timeout_seconds ?? 60);
  const [enabled, setEnabled] = useState(isEnabled(model.enabled));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDisplayName(model.display_name ?? '');
    setProvider(model.provider ?? 'openai_compatible');
    setBaseUrl(model.base_url ?? '');
    setApiKey('');
    setTimeout(model.timeout_seconds ?? 60);
    setEnabled(isEnabled(model.enabled));
    setError(null);
  }, [open, model]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: UpdateGenerationModelRequest = {
        display_name: displayName.trim() || null,
        provider,
        base_url: baseUrl,
        timeout_seconds: timeout,
        enabled,
      };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      return api.updateGenerationModel(model.model_id, payload);
    },
    onSuccess: async () => {
      setError(null);
      await onSaved();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось сохранить модель');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={`Изменить модель «${model.model_id}»`} size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          saveMutation.mutate();
        }}
      >
        <div>
          <span className="mb-1 block text-sm font-medium text-text">model_id</span>
          <Input value={model.model_id} disabled className="font-mono" />
        </div>

        <SelectWrapper label="Провайдер">
          <Select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            options={EMBEDDING_PROVIDERS}
          />
        </SelectWrapper>

        <Field label="Отображаемое имя">
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Field>

        <Field label="Base URL">
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
        </Field>

        <Field label="API ключ" hint="Оставьте пустым, чтобы не менять">
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </Field>

        <Field label="Timeout (сек)">
          <Input
            type="number"
            value={timeout}
            min={1}
            onChange={(e) => setTimeout(Number(e.target.value) || 0)}
          />
        </Field>

        <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} label="Модель включена" />

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={onClose} disabled={saveMutation.isPending}>
            Отмена
          </Button>
          <Button type="submit" loading={saveMutation.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface CreateGenerationModelInlineProps {
  onCreated: () => void;
  onClose: () => void;
}

function CreateGenerationModelInline({ onCreated, onClose }: CreateGenerationModelInlineProps) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['models', 'generation'] });
    void queryClient.invalidateQueries({ queryKey: ['model-health'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
  };
  return (
    <CreateGenerationModelModal
      open
      onClose={onClose}
      onCreated={() => {
        invalidate();
        onCreated();
      }}
    />
  );
}

interface CreateGenerationModelModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function CreateGenerationModelModal({ open, onClose, onCreated }: CreateGenerationModelModalProps) {
  const [modelId, setModelId] = useState('');
  const [provider, setProvider] = useState('openai_compatible');
  const [displayName, setDisplayName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [timeout, setTimeout] = useState(60);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setModelId('');
    setProvider('openai_compatible');
    setDisplayName('');
    setBaseUrl('');
    setApiKey('');
    setTimeout(60);
    setEnabled(true);
    setError(null);
  }, [open]);

  const createMutation = useMutation({
    mutationFn: () => {
      const payload: CreateGenerationModelRequest = {
        model_id: modelId,
        provider,
        display_name: displayName.trim() || null,
        base_url: baseUrl,
        api_key: apiKey.trim() || null,
        timeout_seconds: timeout,
        enabled,
      };
      return api.createGenerationModel(payload);
    },
    onSuccess: () => {
      setError(null);
      onClose();
      onCreated();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось создать модель');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Новая генеративная модель" size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          createMutation.mutate();
        }}
      >
        <Field label="model_id">
          <Input
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            placeholder="gpt-4o"
            className="font-mono"
          />
        </Field>

        <SelectWrapper label="Провайдер">
          <Select value={provider} onChange={(e) => setProvider(e.target.value)} options={EMBEDDING_PROVIDERS} />
        </SelectWrapper>

        <Field label="Отображаемое имя">
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Field>

        <Field label="Base URL">
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
        </Field>

        <Field label="API ключ">
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </Field>

        <Field label="Timeout (сек)">
          <Input type="number" value={timeout} min={1} onChange={(e) => setTimeout(Number(e.target.value) || 0)} />
        </Field>

        <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} label="Модель включена" />

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={onClose} disabled={createMutation.isPending}>
            Отмена
          </Button>
          <Button
            type="submit"
            disabled={!modelId || createMutation.isPending}
            loading={createMutation.isPending}
          >
            Создать
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function EmbeddingModelsBody() {
  const queryClient = useQueryClient();
  const modelsQuery = useQuery({
    queryKey: ['models', 'embedding'],
    queryFn: () => api.getEmbeddingModels(),
  });
  const vaultsQuery = useQuery({
    queryKey: ['settings-vaults'],
    queryFn: () => api.getVaults(),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['models', 'embedding'] });
    void queryClient.invalidateQueries({ queryKey: ['settings-vaults'] });
    void queryClient.invalidateQueries({ queryKey: ['model-health'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
  };

  const linkedCounts = new Map<string, number>();
  for (const v of vaultsQuery.data ?? []) {
    if (v.embedding_model_id) {
      linkedCounts.set(v.embedding_model_id, (linkedCounts.get(v.embedding_model_id) ?? 0) + 1);
    }
  }

  if (modelsQuery.isLoading) {
    return <p className="text-sm text-text-muted">Загрузка…</p>;
  }
  const models = modelsQuery.data ?? [];
  if (models.length === 0) {
    return (
      <EmptyState
        title="Нет embedding-моделей"
        description="Создайте первую модель через кнопку «Добавить» сверху"
      />
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
      {models.map((m) => (
        <EmbeddingModelCard
          key={m.model_id}
          model={m}
          linkedVaults={linkedCounts.get(m.model_id) ?? 0}
          onChanged={invalidate}
        />
      ))}
    </div>
  );
}

interface EmbeddingModelCardProps {
  model: EmbeddingModel;
  linkedVaults: number;
  onChanged: () => void;
}

function EmbeddingModelCard({ model, linkedVaults, onChanged }: EmbeddingModelCardProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [checkResult, setCheckResult] = useState<ModelCheckResult | null>(null);

  const isEnabled = model.enabled !== false;
  const providerStr = [model.provider, model.dimensions ? `${model.dimensions}d` : null]
    .filter(Boolean)
    .join(' · ');

  const checkMutation = useMutation({
    mutationFn: () => api.checkEmbeddingModel(model.model_id),
    onSuccess: (res) => setCheckResult(res),
    onError: (err) =>
      setCheckResult({
        ok: false,
        error: err instanceof HttpError ? err.message : 'Не удалось выполнить проверку',
      }),
  });

  const badges = <StatusBadge kind={isEnabled ? 'ready' : 'disabled'} />;

  const menu: SettingsCardMenuItem[] = [
    { key: 'edit', label: 'Изменить', onClick: () => setEditOpen(true) },
    {
      key: 'check',
      label: checkMutation.isPending ? 'Проверка…' : 'Проверить',
      disabled: checkMutation.isPending,
      onClick: () => {
        setCheckResult(null);
        checkMutation.mutate();
      },
    },
    {
      key: 'delete',
      label: 'Удалить',
      danger: true,
      disabled: linkedVaults > 0,
      onClick: () => setDeleteOpen(true),
    },
  ];

  return (
    <>
      <SettingsCard
        title={model.display_name ?? model.model_id}
        badges={badges}
        subtitle={providerStr}
        meta={
          linkedVaults > 0 ? (
            <span className="text-xs text-text-muted">{linkedVaults} vault(ов) используют модель</span>
          ) : undefined
        }
        active={isEnabled}
        menu={menu}
      />

      <EditEmbeddingModelModal
        open={editOpen}
        model={model}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          setEditOpen(false);
          onChanged();
        }}
      />

      <DeleteModelModal
        open={deleteOpen}
        title="Удалить embedding-модель"
        name={model.display_name ?? model.model_id}
        onClose={() => setDeleteOpen(false)}
        onConfirm={() => api.deleteEmbeddingModel(model.model_id)}
        onDeleted={onChanged}
      />

      <CheckResultModal
        open={!!checkResult || checkMutation.isPending}
        pending={checkMutation.isPending}
        result={checkResult}
        onClose={() => setCheckResult(null)}
        title={`Проверка модели «${model.display_name ?? model.model_id}»`}
      />
    </>
  );
}

interface EditEmbeddingModelModalProps {
  open: boolean;
  model: EmbeddingModel;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

function EditEmbeddingModelModal({ open, model, onClose, onSaved }: EditEmbeddingModelModalProps) {
  const [displayName, setDisplayName] = useState(model.display_name ?? '');
  const [provider, setProvider] = useState(model.provider ?? 'openai_compatible');
  const [modelName, setModelName] = useState(model.model_name ?? '');
  const [baseUrl, setBaseUrl] = useState(model.base_url ?? '');
  const [apiKey, setApiKey] = useState('');
  const [dimensions, setDimensions] = useState(model.dimensions ?? 1536);
  const [timeout, setTimeout] = useState(model.timeout_seconds ?? 30);
  const [maxRetries, setMaxRetries] = useState(model.max_retries ?? 3);
  const [enabled, setEnabled] = useState(isEnabled(model.enabled));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDisplayName(model.display_name ?? '');
    setProvider(model.provider ?? 'openai_compatible');
    setModelName(model.model_name ?? '');
    setBaseUrl(model.base_url ?? '');
    setApiKey('');
    setDimensions(model.dimensions ?? 1536);
    setTimeout(model.timeout_seconds ?? 30);
    setMaxRetries(model.max_retries ?? 3);
    setEnabled(isEnabled(model.enabled));
    setError(null);
  }, [open, model]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: UpdateEmbeddingModelRequest = {
        display_name: displayName.trim() || null,
        provider,
        model_name: modelName.trim() || null,
        base_url: baseUrl,
        dimensions,
        timeout_seconds: timeout,
        max_retries: maxRetries,
        enabled,
      };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      return api.updateEmbeddingModel(model.model_id, payload);
    },
    onSuccess: async () => {
      setError(null);
      await onSaved();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось сохранить модель');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={`Изменить embedding-модель «${model.model_id}»`} size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          saveMutation.mutate();
        }}
      >
        <div>
          <span className="mb-1 block text-sm font-medium text-text">model_id</span>
          <Input value={model.model_id} disabled className="font-mono" />
        </div>

        <SelectWrapper label="Провайдер">
          <Select value={provider} onChange={(e) => setProvider(e.target.value)} options={EMBEDDING_PROVIDERS} />
        </SelectWrapper>

        <Field label="Отображаемое имя">
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Field>

        <Field label="Model name">
          <Input value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="text-embedding-3-small" />
        </Field>

        <Field label="Base URL">
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </Field>

        <Field label="API ключ" hint="Оставьте пустым, чтобы не менять">
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </Field>

        <div className="grid grid-cols-3 gap-3">
          <Field label="Dimensions">
            <Input type="number" value={dimensions} min={1} onChange={(e) => setDimensions(Number(e.target.value) || 0)} />
          </Field>
          <Field label="Timeout (сек)">
            <Input type="number" value={timeout} min={1} onChange={(e) => setTimeout(Number(e.target.value) || 0)} />
          </Field>
          <Field label="Max retries">
            <Input type="number" value={maxRetries} min={0} onChange={(e) => setMaxRetries(Number(e.target.value) || 0)} />
          </Field>
        </div>

        <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} label="Модель включена" />

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={onClose} disabled={saveMutation.isPending}>
            Отмена
          </Button>
          <Button type="submit" loading={saveMutation.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface CreateEmbeddingModelInlineProps {
  onCreated: () => void;
  onClose: () => void;
}

function CreateEmbeddingModelInline({ onCreated, onClose }: CreateEmbeddingModelInlineProps) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['models', 'embedding'] });
    void queryClient.invalidateQueries({ queryKey: ['settings-vaults'] });
    void queryClient.invalidateQueries({ queryKey: ['model-health'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
  };
  return (
    <CreateEmbeddingModelModal
      open
      onClose={onClose}
      onCreated={() => {
        invalidate();
        onCreated();
      }}
    />
  );
}

interface CreateEmbeddingModelModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function CreateEmbeddingModelModal({ open, onClose, onCreated }: CreateEmbeddingModelModalProps) {
  const [modelId, setModelId] = useState('');
  const [provider, setProvider] = useState('openai_compatible');
  const [displayName, setDisplayName] = useState('');
  const [modelName, setModelName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [dimensions, setDimensions] = useState(1536);
  const [timeout, setTimeout] = useState(30);
  const [maxRetries, setMaxRetries] = useState(3);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setModelId('');
    setProvider('openai_compatible');
    setDisplayName('');
    setModelName('');
    setBaseUrl('');
    setApiKey('');
    setDimensions(1536);
    setTimeout(30);
    setMaxRetries(3);
    setEnabled(true);
    setError(null);
  }, [open]);

  const createMutation = useMutation({
    mutationFn: () => {
      const payload: CreateEmbeddingModelRequest = {
        model_id: modelId,
        provider,
        display_name: displayName.trim() || null,
        model_name: modelName.trim() || null,
        base_url: baseUrl,
        api_key: apiKey.trim() || null,
        dimensions,
        timeout_seconds: timeout,
        max_retries: maxRetries,
        enabled,
      };
      return api.createEmbeddingModel(payload);
    },
    onSuccess: () => {
      setError(null);
      onClose();
      onCreated();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось создать модель');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Новая embedding-модель" size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          createMutation.mutate();
        }}
      >
        <Field label="model_id">
          <Input value={modelId} onChange={(e) => setModelId(e.target.value)} className="font-mono" />
        </Field>

        <SelectWrapper label="Провайдер">
          <Select value={provider} onChange={(e) => setProvider(e.target.value)} options={EMBEDDING_PROVIDERS} />
        </SelectWrapper>

        <Field label="Отображаемое имя">
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Field>

        <Field label="Model name">
          <Input value={modelName} onChange={(e) => setModelName(e.target.value)} />
        </Field>

        <Field label="Base URL">
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </Field>

        <Field label="API ключ">
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </Field>

        <div className="grid grid-cols-3 gap-3">
          <Field label="Dimensions">
            <Input type="number" value={dimensions} min={1} onChange={(e) => setDimensions(Number(e.target.value) || 0)} />
          </Field>
          <Field label="Timeout (сек)">
            <Input type="number" value={timeout} min={1} onChange={(e) => setTimeout(Number(e.target.value) || 0)} />
          </Field>
          <Field label="Max retries">
            <Input type="number" value={maxRetries} min={0} onChange={(e) => setMaxRetries(Number(e.target.value) || 0)} />
          </Field>
        </div>

        <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} label="Модель включена" />

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={onClose} disabled={createMutation.isPending}>
            Отмена
          </Button>
          <Button
            type="submit"
            disabled={!modelId || createMutation.isPending}
            loading={createMutation.isPending}
          >
            Создать
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function RerankModelsBody() {
  const queryClient = useQueryClient();
  const modelsQuery = useQuery({
    queryKey: ['models', 'rerank'],
    queryFn: () => api.getRerankModels(),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['models', 'rerank'] });
    void queryClient.invalidateQueries({ queryKey: ['model-health'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
  };

  if (modelsQuery.isLoading) {
    return <p className="text-sm text-text-muted">Загрузка…</p>;
  }
  const models = modelsQuery.data ?? [];
  if (models.length === 0) {
    return (
      <EmptyState
        title="Нет rerank-моделей"
        description="Создайте первую модель через кнопку «Добавить» сверху"
      />
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
      {models.map((m) => (
        <RerankModelCard key={m.model_id} model={m} onChanged={invalidate} />
      ))}
    </div>
  );
}

interface RerankModelCardProps {
  model: RerankModel;
  onChanged: () => void;
}

function RerankModelCard({ model, onChanged }: RerankModelCardProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [checkResult, setCheckResult] = useState<ModelCheckResult | null>(null);

  const isActive = !!model.is_active;
  const isEnabled = model.enabled !== false;

  const activateMutation = useMutation({
    mutationFn: () => api.setActiveRerankModel(model.model_id),
    onSuccess: onChanged,
  });
  const deactivateMutation = useMutation({
    mutationFn: () => api.deactivateRerankModel(model.model_id),
    onSuccess: onChanged,
  });
  const checkMutation = useMutation({
    mutationFn: () => api.checkRerankModel(model.model_id),
    onSuccess: (res) => setCheckResult(res),
    onError: (err) =>
      setCheckResult({
        ok: false,
        error: err instanceof HttpError ? err.message : 'Не удалось выполнить проверку',
      }),
  });

  const badges = <ModelStatusBadge isActive={isActive} isEnabled={isEnabled} />;

  const menu: SettingsCardMenuItem[] = [
    { key: 'edit', label: 'Изменить', onClick: () => setEditOpen(true) },
    {
      key: 'check',
      label: checkMutation.isPending ? 'Проверка…' : 'Проверить',
      disabled: checkMutation.isPending,
      onClick: () => {
        setCheckResult(null);
        checkMutation.mutate();
      },
    },
  ];
  if (isActive) {
    menu.push({
      key: 'deactivate',
      label: 'Деактивировать',
      onClick: () => deactivateMutation.mutate(),
    });
  } else {
    menu.push({
      key: 'activate',
      label: 'Активировать',
      onClick: () => activateMutation.mutate(),
    });
  }
  menu.push({
    key: 'delete',
    label: 'Удалить',
    danger: true,
    disabled: isActive,
    onClick: () => setDeleteOpen(true),
  });

  return (
    <>
      <SettingsCard
        title={model.display_name ?? model.model_id}
        badges={badges}
        subtitle={model.provider}
        active={isActive}
        menu={menu}
      />

      <EditRerankModelModal
        open={editOpen}
        model={model}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          setEditOpen(false);
          onChanged();
        }}
      />

      <DeleteModelModal
        open={deleteOpen}
        title="Удалить rerank-модель"
        name={model.display_name ?? model.model_id}
        onClose={() => setDeleteOpen(false)}
        onConfirm={() => api.deleteRerankModel(model.model_id)}
        onDeleted={onChanged}
      />

      <CheckResultModal
        open={!!checkResult || checkMutation.isPending}
        pending={checkMutation.isPending}
        result={checkResult}
        onClose={() => setCheckResult(null)}
        title={`Проверка модели «${model.display_name ?? model.model_id}»`}
      />
    </>
  );
}

interface EditRerankModelModalProps {
  open: boolean;
  model: RerankModel;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

function EditRerankModelModal({ open, model, onClose, onSaved }: EditRerankModelModalProps) {
  const [displayName, setDisplayName] = useState(model.display_name ?? '');
  const [provider, setProvider] = useState(model.provider ?? 'openai_compatible');
  const [baseUrl, setBaseUrl] = useState(model.base_url ?? '');
  const [apiKey, setApiKey] = useState('');
  const [timeout, setTimeout] = useState(model.timeout_seconds ?? 30);
  const [enabled, setEnabled] = useState(isEnabled(model.enabled));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDisplayName(model.display_name ?? '');
    setProvider(model.provider ?? 'openai_compatible');
    setBaseUrl(model.base_url ?? '');
    setApiKey('');
    setTimeout(model.timeout_seconds ?? 30);
    setEnabled(isEnabled(model.enabled));
    setError(null);
  }, [open, model]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: UpdateRerankModelRequest = {
        display_name: displayName.trim() || null,
        provider,
        base_url: baseUrl,
        timeout_seconds: timeout,
        enabled,
      };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      return api.updateRerankModel(model.model_id, payload);
    },
    onSuccess: async () => {
      setError(null);
      await onSaved();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось сохранить модель');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title={`Изменить rerank-модель «${model.model_id}»`} size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          saveMutation.mutate();
        }}
      >
        <div>
          <span className="mb-1 block text-sm font-medium text-text">model_id</span>
          <Input value={model.model_id} disabled className="font-mono" />
        </div>

        <SelectWrapper label="Провайдер">
          <Select value={provider} onChange={(e) => setProvider(e.target.value)} options={RERANK_PROVIDERS} />
        </SelectWrapper>

        <Field label="Отображаемое имя">
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Field>

        <Field label="Base URL">
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </Field>

        <Field label="API ключ" hint="Оставьте пустым, чтобы не менять">
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </Field>

        <Field label="Timeout (сек)">
          <Input type="number" value={timeout} min={1} onChange={(e) => setTimeout(Number(e.target.value) || 0)} />
        </Field>

        <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} label="Модель включена" />

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={onClose} disabled={saveMutation.isPending}>
            Отмена
          </Button>
          <Button type="submit" loading={saveMutation.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface CreateRerankModelInlineProps {
  onCreated: () => void;
  onClose: () => void;
}

function CreateRerankModelInline({ onCreated, onClose }: CreateRerankModelInlineProps) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['models', 'rerank'] });
    void queryClient.invalidateQueries({ queryKey: ['model-health'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
  };
  return (
    <CreateRerankModelModal
      open
      onClose={onClose}
      onCreated={() => {
        invalidate();
        onCreated();
      }}
    />
  );
}

interface CreateRerankModelModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function CreateRerankModelModal({ open, onClose, onCreated }: CreateRerankModelModalProps) {
  const [modelId, setModelId] = useState('');
  const [provider, setProvider] = useState('openai_compatible');
  const [displayName, setDisplayName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [timeout, setTimeout] = useState(30);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setModelId('');
    setProvider('openai_compatible');
    setDisplayName('');
    setBaseUrl('');
    setApiKey('');
    setTimeout(30);
    setEnabled(true);
    setError(null);
  }, [open]);

  const createMutation = useMutation({
    mutationFn: () => {
      const payload: CreateRerankModelRequest = {
        model_id: modelId,
        provider,
        display_name: displayName.trim() || null,
        base_url: baseUrl,
        api_key: apiKey.trim() || null,
        timeout_seconds: timeout,
        enabled,
      };
      return api.createRerankModel(payload);
    },
    onSuccess: () => {
      setError(null);
      onClose();
      onCreated();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось создать модель');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Новая rerank-модель" size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          createMutation.mutate();
        }}
      >
        <Field label="model_id">
          <Input value={modelId} onChange={(e) => setModelId(e.target.value)} className="font-mono" />
        </Field>

        <SelectWrapper label="Провайдер">
          <Select value={provider} onChange={(e) => setProvider(e.target.value)} options={RERANK_PROVIDERS} />
        </SelectWrapper>

        <Field label="Отображаемое имя">
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Field>

        <Field label="Base URL">
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </Field>

        <Field label="API ключ">
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </Field>

        <Field label="Timeout (сек)">
          <Input type="number" value={timeout} min={1} onChange={(e) => setTimeout(Number(e.target.value) || 0)} />
        </Field>

        <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} label="Модель включена" />

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={onClose} disabled={createMutation.isPending}>
            Отмена
          </Button>
          <Button
            type="submit"
            disabled={!modelId || createMutation.isPending}
            loading={createMutation.isPending}
          >
            Создать
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// =============================================================================
// Drift-модели (Phase 2a)
// =============================================================================

function DriftModelsBody() {
  const queryClient = useQueryClient();
  const modelsQuery = useQuery({
    queryKey: ['models', 'drift'],
    queryFn: () => api.getDriftModels(),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['models', 'drift'] });
    void queryClient.invalidateQueries({ queryKey: ['model-health'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
  };

  if (modelsQuery.isLoading) {
    return <p className="text-sm text-text-muted">Загрузка…</p>;
  }
  const models = modelsQuery.data ?? [];
  if (models.length === 0) {
    return (
      <EmptyState
        title="Нет drift-моделей"
        description="Создайте первую модель через кнопку «Добавить» сверху"
      />
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
      {models.map((m) => (
        <DriftModelCard key={m.model_id} model={m} onChanged={invalidate} />
      ))}
    </div>
  );
}

interface DriftModelCardProps {
  model: DriftModel;
  onChanged: () => void;
}

function DriftModelCard({ model, onChanged }: DriftModelCardProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [checkResult, setCheckResult] = useState<ModelCheckResult | null>(null);

  const isActive = !!model.is_active;
  const isEnabled = model.enabled !== false;

  const activateMutation = useMutation({
    mutationFn: () => api.setActiveDriftModel(model.model_id),
    onSuccess: onChanged,
  });
  const deactivateMutation = useMutation({
    mutationFn: () => api.deactivateDriftModel(model.model_id),
    onSuccess: onChanged,
  });
  const checkMutation = useMutation({
    mutationFn: () => api.checkDriftModel(model.model_id),
    onSuccess: (res) => setCheckResult(res),
    onError: (err) =>
      setCheckResult({
        ok: false,
        error: err instanceof HttpError ? err.message : 'Не удалось выполнить проверку',
      }),
  });

  const badges = <ModelStatusBadge isActive={isActive} isEnabled={isEnabled} />;

  const menu: SettingsCardMenuItem[] = [
    { key: 'edit', label: 'Изменить', onClick: () => setEditOpen(true) },
    {
      key: 'check',
      label: checkMutation.isPending ? 'Проверка…' : 'Проверить',
      disabled: checkMutation.isPending,
      onClick: () => {
        setCheckResult(null);
        checkMutation.mutate();
      },
    },
    ...(isActive
      ? ([
          {
            key: 'deactivate',
            label: deactivateMutation.isPending ? 'Деактивация…' : 'Деактивировать',
            disabled: deactivateMutation.isPending,
            onClick: () => deactivateMutation.mutate(),
          },
        ] as SettingsCardMenuItem[])
      : isEnabled
        ? ([
            {
              key: 'activate',
              label: activateMutation.isPending ? 'Активация…' : 'Активировать',
              disabled: activateMutation.isPending,
              onClick: () => activateMutation.mutate(),
            },
          ] as SettingsCardMenuItem[])
        : []),
    ...(!isActive
      ? ([
          {
            key: 'delete',
            label: 'Удалить',
            danger: true,
            onClick: () => setDeleteOpen(true),
          },
        ] as SettingsCardMenuItem[])
      : []),
  ];

  const providerLabel =
    model.provider === 'host_sidecar'
      ? 'Sidecar'
      : model.provider === 'openai_compatible'
        ? 'OpenAI compatible'
        : model.provider ?? '—';

  return (
    <>
      <SettingsCard
        title={model.display_name || model.model_id}
        subtitle={`${providerLabel} · ${model.model_name ?? '—'}`}
        badges={badges}
        menu={menu}
      />
      {editOpen && (
        <EditDriftModelModal
          model={model}
          onClose={() => setEditOpen(false)}
          onSaved={() => {
            setEditOpen(false);
            onChanged();
          }}
        />
      )}
      {deleteOpen && (
        <DeleteModelModal
          open
          title="Удалить drift-модель"
          name={model.display_name || model.model_id}
          onClose={() => setDeleteOpen(false)}
          onConfirm={() => api.deleteDriftModel(model.model_id)}
          onDeleted={() => {
            setDeleteOpen(false);
            onChanged();
          }}
        />
      )}
      {checkResult !== null && (
        <CheckResultModal
          open
          pending={checkMutation.isPending}
          result={checkResult}
          title={`Проверка: ${model.display_name || model.model_id}`}
          onClose={() => setCheckResult(null)}
        />
      )}
    </>
  );
}

interface EditDriftModelModalProps {
  model: DriftModel;
  onClose: () => void;
  onSaved: () => void;
}

function EditDriftModelModal({ model, onClose, onSaved }: EditDriftModelModalProps) {
  const [provider, setProvider] = useState(model.provider ?? 'host_sidecar');
  const [baseUrl, setBaseUrl] = useState(model.base_url ?? '');
  const [modelName, setModelName] = useState(model.model_name ?? '');
  const [displayName, setDisplayName] = useState(model.display_name ?? '');
  const [apiKey, setApiKey] = useState('');
  const [timeout, setTimeout] = useState(model.timeout_seconds ?? 60);
  const [enabled, setEnabled] = useState(model.enabled !== false);
  const [error, setError] = useState<string | null>(null);

  const updateMutation = useMutation({
    mutationFn: () => {
      const payload: UpdateDriftModelRequest = {
        provider,
        base_url: baseUrl.trim() || null,
        model_name: modelName.trim() || undefined,
        display_name: displayName.trim() || null,
        api_key: apiKey.trim() ? apiKey.trim() : null,
        timeout_seconds: timeout,
        enabled,
      };
      return api.updateDriftModel(model.model_id, payload);
    },
    onSuccess: () => {
      setError(null);
      onSaved();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось обновить модель');
    },
  });

  return (
    <Modal open onClose={onClose} title={`Изменить drift-модель: ${model.model_id}`} size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          updateMutation.mutate();
        }}
      >
        <SelectWrapper label="Провайдер">
          <Select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            options={DRIFT_PROVIDERS}
          />
        </SelectWrapper>

        {provider === 'host_sidecar' && (
          <Field label="Base URL (pdf-sidecar)">
            <Input
              value={baseUrl}
              placeholder={DEFAULT_DRIFT_SIDECAR_URL}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </Field>
        )}
        {provider === 'openai_compatible' && (
          <>
            <Field label="Base URL">
              <Input
                value={baseUrl}
                placeholder="https://api.example.com/v1"
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </Field>
            <Field label="API ключ (оставьте пустым чтобы не менять)">
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </Field>
          </>
        )}

        <Field label="Model name">
          <Input value={modelName} onChange={(e) => setModelName(e.target.value)} className="font-mono" />
        </Field>

        <Field label="Отображаемое имя">
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Field>

        <Field label="Timeout (сек)">
          <Input
            type="number"
            value={timeout}
            min={1}
            onChange={(e) => setTimeout(Number(e.target.value) || 0)}
          />
        </Field>

        <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} label="Модель включена" />

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={onClose} disabled={updateMutation.isPending}>
            Отмена
          </Button>
          <Button type="submit" loading={updateMutation.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface CreateDriftModelInlineProps {
  onCreated: () => void;
  onClose: () => void;
}

function CreateDriftModelInline({ onCreated, onClose }: CreateDriftModelInlineProps) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['models', 'drift'] });
    void queryClient.invalidateQueries({ queryKey: ['model-health'] });
    void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
  };
  return (
    <CreateDriftModelModal
      open
      onClose={onClose}
      onCreated={() => {
        invalidate();
        onCreated();
      }}
    />
  );
}

interface CreateDriftModelModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function CreateDriftModelModal({ open, onClose, onCreated }: CreateDriftModelModalProps) {
  const [modelId, setModelId] = useState('');
  const [provider, setProvider] = useState('host_sidecar');
  const [baseUrl, setBaseUrl] = useState(DEFAULT_DRIFT_SIDECAR_URL);
  const [modelName, setModelName] = useState('qwen2.5-3b-instruct-q4_k_m');
  const [displayName, setDisplayName] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [timeout, setTimeout] = useState(60);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setModelId('');
    setProvider('host_sidecar');
    setBaseUrl(DEFAULT_DRIFT_SIDECAR_URL);
    setModelName('qwen2.5-3b-instruct-q4_k_m');
    setDisplayName('');
    setApiKey('');
    setTimeout(60);
    setEnabled(true);
    setError(null);
  }, [open]);

  const createMutation = useMutation({
    mutationFn: () => {
      const payload: CreateDriftModelRequest = {
        model_id: modelId,
        provider,
        base_url: baseUrl.trim() || null,
        model_name: modelName.trim(),
        display_name: displayName.trim() || null,
        api_key: apiKey.trim() || null,
        timeout_seconds: timeout,
        enabled,
      };
      return api.createDriftModel(payload);
    },
    onSuccess: () => {
      setError(null);
      onClose();
      onCreated();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось создать модель');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Новая drift-модель" size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          createMutation.mutate();
        }}
      >
        <Field label="model_id">
          <Input
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            className="font-mono"
            placeholder="drift-local-default"
          />
        </Field>

        <SelectWrapper label="Провайдер">
          <Select
            value={provider}
            onChange={(e) => {
              const next = e.target.value;
              setProvider(next);
              if (next === 'host_sidecar') setBaseUrl(DEFAULT_DRIFT_SIDECAR_URL);
            }}
            options={DRIFT_PROVIDERS}
          />
        </SelectWrapper>

        {provider === 'host_sidecar' && (
          <Field label="Base URL (pdf-sidecar)">
            <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </Field>
        )}
        {provider === 'openai_compatible' && (
          <>
            <Field label="Base URL">
              <Input
                value={baseUrl}
                placeholder="https://api.example.com/v1"
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </Field>
            <Field label="API ключ">
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </Field>
          </>
        )}

        <Field label="Model name">
          <Input value={modelName} onChange={(e) => setModelName(e.target.value)} className="font-mono" />
        </Field>

        <Field label="Отображаемое имя">
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Field>

        <Field label="Timeout (сек)">
          <Input
            type="number"
            value={timeout}
            min={1}
            onChange={(e) => setTimeout(Number(e.target.value) || 0)}
          />
        </Field>

        <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} label="Модель включена" />

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={onClose} disabled={createMutation.isPending}>
            Отмена
          </Button>
          <Button
            type="submit"
            disabled={!modelId || !modelName.trim() || createMutation.isPending}
            loading={createMutation.isPending}
          >
            Создать
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface DeleteModelModalProps {
  open: boolean;
  title: string;
  name: string;
  onClose: () => void;
  onConfirm: () => Promise<unknown>;
  onDeleted: () => void;
}

function DeleteModelModal({ open, title, name, onClose, onConfirm, onDeleted }: DeleteModelModalProps) {
  const [error, setError] = useState<string | null>(null);
  const deleteMutation = useMutation({
    mutationFn: onConfirm,
    onSuccess: () => {
      setError(null);
      onClose();
      onDeleted();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось удалить модель');
    },
  });

  return (
    <ConfirmModal
      open={open}
      title={title}
      message={
        <>
          Удалить модель <span className="font-semibold">{name}</span>? Действие необратимо.
        </>
      }
      pending={deleteMutation.isPending}
      error={error}
      onConfirm={() => {
        setError(null);
        deleteMutation.mutate();
      }}
      onClose={onClose}
    />
  );
}

interface CheckResultModalProps {
  open: boolean;
  pending: boolean;
  result: ModelCheckResult | null;
  title: string;
  onClose: () => void;
}

function CheckResultModal({ open, pending, result, title, onClose }: CheckResultModalProps) {
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm">
      <div className="space-y-3 p-4 text-sm">
        {pending ? (
          <p className="text-text-muted">Проверка соединения…</p>
        ) : result ? (
          <>
            <div
              className={
                result.ok
                  ? 'rounded border border-success/30 bg-success/10 px-3 py-2 text-success'
                  : 'rounded border border-danger/30 bg-danger/10 px-3 py-2 text-danger'
              }
            >
              {result.ok ? 'Соединение успешно' : 'Ошибка соединения'}
            </div>
            {result.latency_ms !== undefined && (
              <p className="text-text-muted">Латентность: {result.latency_ms} мс</p>
            )}
            {result.dimensions !== undefined && result.dimensions !== null && (
              <p className="text-text-muted">Размерность: {result.dimensions}</p>
            )}
            {result.error && <p className="text-danger">{result.error}</p>}
          </>
        ) : null}
        <div className="flex justify-end">
          <Button variant="ghost" onClick={onClose}>
            Закрыть
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function isEnabled(value: boolean | undefined | null): boolean {
  return value !== false;
}

// re-export
export type { ModelKind, Vault };