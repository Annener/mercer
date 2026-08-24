import { useEffect, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Badge,
  Button,
  ConfirmModal,
  EmptyState,
  Field,
  Input,
  Modal,
  SettingsCard,
  StatusBadge,
  Textarea,
  type SettingsCardMenuItem,
} from '@/components/ui';
import { api } from '@/api/client';
import { HttpError } from '@/api/http';
import type { Domain, PromptType } from '@/api/types';

const PROMPT_TYPES: ReadonlyArray<{ id: PromptType; label: string }> = [
  { id: 'system', label: 'Системный' },
  { id: 'clarification', label: 'Clarification' },
  { id: 'planner', label: 'Planner' },
  { id: 'pipeline_router', label: 'Pipeline Router' },
];

export function DomainsTab() {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);

  const domainsQuery = useQuery({
    queryKey: ['settings-domains'],
    queryFn: () => api.getSettingsDomains(),
  });

  const domains = domainsQuery.data ?? [];

  const refetch = () => {
    void queryClient.invalidateQueries({ queryKey: ['settings-domains'] });
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setCreating(true)}>+ Новый домен</Button>
      </div>

      <CreateDomainModal
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={refetch}
      />

      {domainsQuery.isLoading ? (
        <p className="text-sm text-text-muted">Загрузка…</p>
      ) : domains.length === 0 ? (
        <EmptyState
          title="Нет доменов"
          description="Создайте первый домен, чтобы начать работу"
          actions={
            <Button size="sm" onClick={() => setCreating(true)}>
              + Новый домен
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
          {domains.map((d) => (
            <DomainTile key={d.domain_id} domain={d} onChanged={refetch} />
          ))}
        </div>
      )}
    </div>
  );
}

interface DomainTileProps {
  domain: Domain;
  onChanged: () => void;
}

function DomainTile({ domain, onChanged }: DomainTileProps) {
  const queryClient = useQueryClient();
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const isEnabled = domain.enabled !== false;

  const toggleMutation = useMutation({
    mutationFn: (next: boolean) =>
      api.updateDomain(domain.domain_id, { enabled: next }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['settings-domains'] });
      onChanged();
    },
  });

  const badges = <StatusBadge kind={isEnabled ? 'active' : 'inactive'} />;

  const menu: SettingsCardMenuItem[] = [
    {
      key: 'edit',
      label: 'Изменить',
      onClick: () => setEditModalOpen(true),
    },
    {
      key: 'toggle',
      label: isEnabled ? 'Деактивировать' : 'Активировать',
      disabled: toggleMutation.isPending,
      onClick: () => toggleMutation.mutate(!isEnabled),
    },
  ];
  if (!domain.is_system) {
    menu.push({
      key: 'delete',
      label: 'Удалить',
      danger: true,
      onClick: () => {
        setDeleteError(null);
        setDeleteConfirmOpen(true);
      },
    });
  }

  return (
    <>
      <SettingsCard
        title={domain.display_name ?? domain.domain_id}
        badges={badges}
        subtitle={domain.domain_id}
        meta={domain.description}
        active={isEnabled}
        menu={menu}
        footer={
          domain.is_system ? (
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="info">Системный</Badge>
            </div>
          ) : null
        }
      />

      <EditDomainModal
        open={editModalOpen}
        domain={domain}
        onClose={() => setEditModalOpen(false)}
        onSaved={async () => {
          setEditModalOpen(false);
          await queryClient.invalidateQueries({ queryKey: ['settings-domains'] });
          onChanged();
        }}
      />

      <DeleteDomainModal
        open={deleteConfirmOpen}
        domain={domain}
        error={deleteError}
        onClose={() => {
          setDeleteConfirmOpen(false);
          setDeleteError(null);
        }}
        onDeleted={async () => {
          setDeleteConfirmOpen(false);
          setDeleteError(null);
          await queryClient.invalidateQueries({ queryKey: ['settings-domains'] });
          onChanged();
        }}
      />
    </>
  );
}

interface EditDomainModalProps {
  open: boolean;
  domain: Domain;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

type PromptMap = Record<PromptType, string>;

function emptyPromptMap(): PromptMap {
  return { system: '', clarification: '', planner: '', pipeline_router: '' };
}

function normalizePrompts(raw: unknown): PromptMap {
  const map = emptyPromptMap();
  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (item && typeof item === 'object' && 'prompt_type' in item && 'content' in item) {
        const t = (item as { prompt_type: PromptType }).prompt_type;
        if (t in map) {
          map[t] = String((item as { content: unknown }).content ?? '');
        }
      }
    }
    return map;
  }
  if (raw && typeof raw === 'object') {
    const obj = raw as Record<string, unknown>;
    for (const t of Object.keys(map) as PromptType[]) {
      if (t in obj) map[t] = String(obj[t] ?? '');
    }
  }
  return map;
}

function EditDomainModal({ open, domain, onClose, onSaved }: EditDomainModalProps) {
  const [name, setName] = useState(domain.display_name ?? '');
  const [description, setDescription] = useState(domain.description ?? '');
  const [enabled, setEnabled] = useState(domain.enabled !== false);
  const [prompts, setPrompts] = useState<PromptMap>(emptyPromptMap());
  const [error, setError] = useState<string | null>(null);

  const promptsQuery = useQuery({
    queryKey: ['domain-prompts', domain.domain_id],
    queryFn: () => api.getDomainPrompts(domain.domain_id),
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    setName(domain.display_name ?? '');
    setDescription(domain.description ?? '');
    setEnabled(domain.enabled !== false);
    setError(null);
  }, [open, domain]);

  useEffect(() => {
    if (promptsQuery.data) {
      setPrompts(normalizePrompts(promptsQuery.data));
    }
  }, [promptsQuery.data]);

  const baseDirty =
    name !== (domain.display_name ?? '') ||
    description !== (domain.description ?? '') ||
    enabled !== (domain.enabled !== false);

  const [originalPrompts, setOriginalPrompts] = useState<PromptMap>(emptyPromptMap());
  useEffect(() => {
    if (promptsQuery.data) {
      const normalized = normalizePrompts(promptsQuery.data);
      setOriginalPrompts(normalized);
      setPrompts(normalized);
    }
  }, [promptsQuery.data]);

  const promptsDirty = PROMPT_TYPES.some((p) => prompts[p.id] !== originalPrompts[p.id]);
  const isDirty = baseDirty || promptsDirty;

  const saveMutation = useMutation({
    mutationFn: async () => {
      const tasks: Array<Promise<unknown>> = [];
      if (baseDirty) {
        tasks.push(
          api.updateDomain(domain.domain_id, {
            display_name: name.trim() || domain.domain_id,
            description: description.trim() ? description.trim() : null,
            enabled,
          }),
        );
      }
      for (const p of PROMPT_TYPES) {
        if (prompts[p.id] !== originalPrompts[p.id]) {
          tasks.push(api.updateDomainPrompt(domain.domain_id, p.id, prompts[p.id]));
        }
      }
      if (tasks.length === 0) return;
      await Promise.all(tasks);
    },
    onSuccess: async () => {
      setError(null);
      await onSaved();
    },
    onError: (err) => {
      const msg = err instanceof HttpError ? err.message : 'Не удалось сохранить домен';
      setError(msg);
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!isDirty || saveMutation.isPending) return;
    setError(null);
    saveMutation.mutate();
  };

  const handleClose = () => {
    if (saveMutation.isPending) return;
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={`Изменить домен «${domain.display_name ?? domain.domain_id}»`}
      size="lg"
    >
      <form className="space-y-4 p-4 text-base" onSubmit={handleSubmit}>
        <div>
          <span className="mb-1 block text-sm font-medium text-text">Slug (domain_id)</span>
          <input
            value={domain.domain_id}
            disabled
            className="w-full cursor-not-allowed rounded border border-border bg-surface-2 px-2 py-1.5 font-mono text-sm text-text-muted"
          />
          <span className="mt-1 block text-xs text-text-muted">
            Идентификатор нельзя изменить после создания.
          </span>
        </div>

        <Field label="Отображаемое имя">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>

        <Field label="Описание">
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
        </Field>

        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="h-4 w-4 rounded border-border"
          />
          <span className="text-sm text-text">Домен активен (доступен в селекторе чата)</span>
        </label>

        <hr className="border-border" />

        <div>
          <h4 className="mb-3 text-base font-semibold text-text">Промпты домена</h4>
          <div className="space-y-3">
            {PROMPT_TYPES.map((p) => (
              <Field key={p.id} label={p.label}>
                <Textarea
                  value={prompts[p.id]}
                  onChange={(e) =>
                    setPrompts((prev) => ({ ...prev, [p.id]: e.target.value }))
                  }
                  rows={4}
                />
              </Field>
            ))}
          </div>
        </div>

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={handleClose} disabled={saveMutation.isPending}>
            Отмена
          </Button>
          <Button type="submit" loading={saveMutation.isPending} disabled={!isDirty || saveMutation.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface DeleteDomainModalProps {
  open: boolean;
  domain: Domain;
  error: string | null;
  onClose: () => void;
  onDeleted: () => Promise<void>;
}

function DeleteDomainModal({ open, domain, error, onClose, onDeleted }: DeleteDomainModalProps) {
  const deleteMutation = useMutation({
    mutationFn: () => api.deleteDomain(domain.domain_id),
    onSuccess: async () => {
      await onDeleted();
    },
  });

  return (
    <ConfirmModal
      open={open}
      title="Удалить домен"
      message={
        <>
          Удалить домен <span className="font-semibold">{domain.display_name ?? domain.domain_id}</span>?
          Действие необратимо.
        </>
      }
      pending={deleteMutation.isPending}
      error={error}
      onConfirm={() => {
        deleteMutation.mutate();
      }}
      onClose={onClose}
    />
  );
}

interface CreateDomainModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function CreateDomainModal({ open, onClose, onCreated }: CreateDomainModalProps) {
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      api.createDomain({
        domain_id: id,
        display_name: name.trim() || id,
        description: description.trim() ? description.trim() : null,
        enabled: true,
      }),
    onSuccess: async () => {
      setId('');
      setName('');
      setDescription('');
      setError(null);
      onClose();
      onCreated();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось создать домен');
    },
  });

  const handleClose = () => {
    if (createMutation.isPending) return;
    setError(null);
    setId('');
    setName('');
    setDescription('');
    onClose();
  };

  return (
    <Modal open={open} onClose={handleClose} title="Новый домен" size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          createMutation.mutate();
        }}
      >
        <Field label="Slug (domain_id)">
          <Input
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="my-domain"
            className="font-mono"
          />
        </Field>
        <span className="-mt-2 block text-xs text-text-muted">
          Только латиница, цифры и подчёркивание, от 3 до 32 символов.
        </span>

        <Field label="Отображаемое имя">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My Domain"
          />
        </Field>

        <Field label="Описание">
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
          />
        </Field>

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" type="button" onClick={handleClose}>
            Отмена
          </Button>
          <Button
            type="submit"
            disabled={!id || createMutation.isPending}
            loading={createMutation.isPending}
          >
            Создать
          </Button>
        </div>
      </form>
    </Modal>
  );
}