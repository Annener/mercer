import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Badge,
  Button,
  Checkbox,
  ConfirmModal,
  EmptyState,
  ErrorBoundary,
  Field,
  Input,
  Modal,
  Select,
  SelectWrapper,
  SettingsCard,
  type SettingsCardMenuItem,
  TagOverflow,
  Textarea,
} from '@/components/ui';
import { api, HttpError } from '@/api/client';
import { useDomainStore, useSettingsStore } from '@/stores';
import { useStateFields } from './useStateFields';
import { InitialStateButton } from './InitialStateButton';
import { EffectiveContextButton } from './EffectiveContextButton';
import { EditFieldValueDialog } from './EditFieldValueDialog';
import type {
  Campaign,
  CampaignId,
  CreateStateFieldRequest,
  DomainId,
  StateFieldMode,
  TagId,
  TagRead,
} from '@/api/types';

export function CampaignsTab() {
  const selectedRailDomainId = useSettingsStore((s) => s.selectedRailDomainId);
  const [creating, setCreating] = useState(false);

  const isAll = selectedRailDomainId === null;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setCreating(true)}>+ Кампания</Button>
      </div>

      <CreateCampaignModal
        open={creating}
        defaultDomainId={selectedRailDomainId}
        onClose={() => setCreating(false)}
      />

      <CampaignsList domainId={isAll ? null : (selectedRailDomainId as DomainId)} />
    </div>
  );
}

interface CampaignsListProps {
  domainId: DomainId | null;
}

function CampaignsList({ domainId }: CampaignsListProps) {
  const queryClient = useQueryClient();
  const campaignsQuery = useQuery({
    queryKey: ['campaigns', domainId],
    queryFn: () => api.getCampaigns(domainId ?? null),
  });

  const list = (campaignsQuery.data && Array.isArray(campaignsQuery.data)
    ? campaignsQuery.data
    : (campaignsQuery.data as { campaigns?: Campaign[] } | undefined)?.campaigns ?? []) as Campaign[];

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['campaigns'] });

  if (campaignsQuery.isLoading) {
    return <p className="text-sm text-text-muted">Загрузка…</p>;
  }

  if (list.length === 0) {
    return (
      <EmptyState
        title={domainId ? 'Нет кампаний в этом домене' : 'Нет кампаний'}
        description="Создайте первую кампанию, чтобы начать работу"
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
      {list.map((c) => (
        <CampaignCard key={c.id} campaign={c} onDeleted={invalidate} />
      ))}
    </div>
  );
}

interface CampaignCardProps {
  campaign: Campaign;
  onDeleted: () => void;
}

function CampaignCard({ campaign, onDeleted }: CampaignCardProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const globalTagsQuery = useQuery({
    queryKey: ['campaign-global-tags', campaign.id],
    queryFn: () => api.getCampaignGlobalTags(campaign.id),
  });

  const ownTags: TagRead[] = campaign.tags ?? [];
  const globalTags: TagRead[] = (globalTagsQuery.data ?? []).filter(
    (t) => !ownTags.some((ot) => ot.id === t.id),
  );

  const menu: SettingsCardMenuItem[] = [
    { key: 'edit', label: 'Изменить', onClick: () => setEditOpen(true) },
    { key: 'delete', label: 'Удалить', danger: true, onClick: () => setDeleteOpen(true) },
  ];

  return (
    <>
      <SettingsCard
        title={campaign.name}
        badges={<Badge variant="info">{campaign.domain_id}</Badge>}
        subtitle={campaign.description ?? undefined}
        active={!!campaign.has_initial_state}
        menu={menu}
        footer={
          <div className="flex flex-col gap-2">
            {ownTags.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase text-text-muted">
                  Свои теги
                </p>
                <TagOverflow tags={ownTags} max={5} emptyHint="—" />
              </div>
            )}
            {globalTags.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase text-text-muted">
                  Глобальные теги
                </p>
                <TagOverflow tags={globalTags} max={5} emptyHint="—" />
              </div>
            )}
          </div>
        }
      />

      {editOpen && (
        <ErrorBoundary
          fallback={(err) => (
            <Modal open onClose={() => setEditOpen(false)} title="Ошибка" size="md">
              <div className="space-y-3 p-4 text-sm">
                <p className="text-danger">Не удалось открыть форму редактирования:</p>
                <pre className="whitespace-pre-wrap rounded bg-surface-2 p-3 text-xs text-text">
                  {err.message}
                </pre>
                <div className="flex justify-end">
                  <Button onClick={() => setEditOpen(false)}>Закрыть</Button>
                </div>
              </div>
            </Modal>
          )}
        >
          <EditCampaignModal
            open={editOpen}
            campaign={campaign}
            onClose={() => setEditOpen(false)}
            onSaved={() => setEditOpen(false)}
          />
        </ErrorBoundary>
      )}

      <DeleteCampaignModal
        open={deleteOpen}
        campaign={campaign}
        onClose={() => setDeleteOpen(false)}
        onDeleted={onDeleted}
      />
    </>
  );
}

interface DeleteCampaignModalProps {
  open: boolean;
  campaign: Campaign;
  onClose: () => void;
  onDeleted: () => void;
}

function DeleteCampaignModal({ open, campaign, onClose, onDeleted }: DeleteCampaignModalProps) {
  const [error, setError] = useState<string | null>(null);
  const deleteMutation = useMutation({
    mutationFn: () => api.deleteCampaign(campaign.id),
    onSuccess: () => {
      setError(null);
      onClose();
      onDeleted();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось удалить кампанию');
    },
  });
  return (
    <ConfirmModal
      open={open}
      title="Удалить кампанию"
      message={
        <>
          Удалить кампанию <span className="font-semibold">{campaign.name}</span>? Действие необратимо.
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

interface CreateCampaignModalProps {
  open: boolean;
  defaultDomainId: DomainId | null;
  onClose: () => void;
}

function CreateCampaignModal({ open, defaultDomainId, onClose }: CreateCampaignModalProps) {
  const domains = useDomainStore((s) => s.domains);
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [domainId, setDomainId] = useState<string>(defaultDomainId ?? '');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName('');
      setDescription('');
      setSystemPrompt('');
      setDomainId(defaultDomainId ?? '');
      setError(null);
    }
  }, [open, defaultDomainId]);

  const domainOptions: Array<{ value: string; label: string }> = domains
    .filter((d) => d.domain_id !== 'default' && d.enabled !== false)
    .map((d) => ({ value: d.domain_id, label: d.display_name ?? d.domain_id }));

  const createMutation = useMutation({
    mutationFn: () =>
      api.createCampaign({
        domain_id: domainId,
        name,
        description,
        system_prompt: systemPrompt,
      }),
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      onClose();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось создать кампанию');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Новая кампания" size="md">
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          createMutation.mutate();
        }}
      >
        <SelectWrapper label="Домен">
          <Select
            value={domainId}
            onChange={(e) => setDomainId(e.target.value)}
            options={domainOptions}
            placeholder="— выберите домен —"
          />
        </SelectWrapper>

        <Field label="Название">
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field label="Описание">
          <Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Field label="System Prompt" hint="Инструкция для AI в этой кампании">
          <Textarea
            rows={5}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            className="font-mono text-xs"
          />
        </Field>

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
            disabled={!name || !domainId || createMutation.isPending}
            loading={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Создать
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface EditCampaignModalProps {
  open: boolean;
  campaign: Campaign;
  onClose: () => void;
  onSaved: () => void;
}

function EditCampaignModal({ open, campaign, onClose, onSaved }: EditCampaignModalProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(campaign.name);
  const [description, setDescription] = useState(campaign.description ?? '');
  const [systemPrompt, setSystemPrompt] = useState(campaign.system_prompt ?? '');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName(campaign.name);
      setDescription(campaign.description ?? '');
      setSystemPrompt(campaign.system_prompt ?? '');
      setError(null);
    }
  }, [open, campaign]);

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateCampaign(campaign.id, {
        name: name.trim(),
        description: description.trim() || null,
        system_prompt: systemPrompt,
      }),
    onSuccess: async () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      onSaved();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось сохранить кампанию');
    },
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Изменить кампанию «${campaign.name}»`}
      size="lg"
    >
      <form
        className="space-y-4 p-4 text-base"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          saveMutation.mutate();
        }}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <span className="mb-1 block text-sm font-medium text-text">ID кампании</span>
            <Input value={campaign.id} disabled className="font-mono text-xs" />
          </div>
          <div>
            <span className="mb-1 block text-sm font-medium text-text">Домен</span>
            <Input value={campaign.domain_id} disabled className="font-mono text-xs" />
          </div>
        </div>

        <Field label="Название">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>

        <Field label="Описание">
          <Textarea
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>

        <Field label="System Prompt" hint="Инструкция для AI в этой кампании">
          <Textarea
            rows={5}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            className="font-mono text-xs"
          />
        </Field>

        <hr className="border-border" />

        <CampaignOwnTagsSection campaign={campaign} />

        <CampaignGlobalTagsSection campaign={campaign} />

        <CampaignStateFieldsSection campaignId={campaign.id} />

        <hr className="border-border" />

        {!campaign.has_initial_state && (
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold">Начальный контекст</h4>
            <InitialStateButton campaignId={campaign.id} />
          </div>
        )}

        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold">Debug</h4>
          <EffectiveContextButton campaignId={campaign.id} />
        </div>

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button
            variant="ghost"
            type="button"
            onClick={onClose}
            disabled={saveMutation.isPending}
          >
            Отмена
          </Button>
          <Button
            type="submit"
            loading={saveMutation.isPending}
            disabled={!name || saveMutation.isPending}
          >
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface CampaignOwnTagsSectionProps {
  campaign: Campaign;
}

function CampaignOwnTagsSection({ campaign }: CampaignOwnTagsSectionProps) {
  const queryClient = useQueryClient();
  const ownTags: TagRead[] = campaign.tags ?? [];
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState('#3498db');
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      api.createCampaignTag(campaign.id, { name: newName.trim(), color: newColor }),
    onSuccess: () => {
      setError(null);
      setNewName('');
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] });
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось создать тег');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (tagId: TagId) => api.deleteTag(tagId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['campaigns'] }),
  });

  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold">Теги кампании</h4>
      <div className="mb-3 flex flex-wrap items-center gap-1">
        {ownTags.length === 0 ? (
          <span className="text-xs text-text-muted">Нет тегов</span>
        ) : (
          ownTags.map((t) => (
            <button
              key={t.id}
              type="button"
              className="group inline-flex items-center rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs font-medium hover:border-danger"
              onClick={() => {
                if (confirm(`Удалить тег «${t.name}»?`)) deleteMutation.mutate(t.id);
              }}
              aria-label={`Удалить тег ${t.name}`}
            >
              <span style={t.color ? { color: t.color } : undefined}>{t.name}</span>
              <span className="ml-1 text-text-muted group-hover:text-danger">×</span>
            </button>
          ))
        )}
      </div>

      <div className="flex flex-wrap items-end gap-2 rounded border border-border bg-surface-2 p-2">
        <Field label="Название" className="flex-1 min-w-[160px]">
          <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Новый тег" />
        </Field>
        <Field label="Цвет">
          <input
            type="color"
            value={newColor}
            onChange={(e) => setNewColor(e.target.value)}
            className="h-8 w-12 cursor-pointer rounded border border-border bg-surface"
          />
        </Field>
        <Button
          size="sm"
          disabled={!newName.trim() || createMutation.isPending}
          loading={createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          + Создать тег
        </Button>
      </div>

      {error && (
        <div className="mt-2 rounded border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}
    </div>
  );
}

interface CampaignGlobalTagsSectionProps {
  campaign: Campaign;
}

function CampaignGlobalTagsSection({ campaign }: CampaignGlobalTagsSectionProps) {
  const queryClient = useQueryClient();
  const globalQuery = useQuery({
    queryKey: ['campaign-global-tags', campaign.id],
    queryFn: () => api.getCampaignGlobalTags(campaign.id),
  });
  const allTagsQuery = useQuery({
    queryKey: ['settings-tags', campaign.domain_id],
    queryFn: async () => {
      // api.getTags возвращает TagsGrouped ({global_tags, by_campaign}) — нам нужны
      // только глобальные теги домена для выпадающего списка.
      const grouped = (await api.getTags(campaign.domain_id)) as unknown as {
        global_tags?: TagRead[];
        by_campaign?: Record<string, TagRead[]>;
      } | TagRead[];
      if (Array.isArray(grouped)) return grouped;
      return grouped.global_tags ?? [];
    },
    enabled: !!campaign.domain_id,
  });

  const ownIds = new Set((campaign.tags ?? []).map((t) => t.id));
  const linked: TagRead[] = (globalQuery.data ?? []).filter((t) => !ownIds.has(t.id));

  const available: TagRead[] = (allTagsQuery.data ?? []).filter(
    (t) => t.campaign_id == null && !ownIds.has(t.id) && !linked.some((l) => l.id === t.id),
  );

  const [error, setError] = useState<string | null>(null);
  const linkMutation = useMutation({
    mutationFn: (tagId: TagId) => api.linkCampaignGlobalTag(campaign.id, tagId),
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['campaign-global-tags', campaign.id] });
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось подключить тег');
    },
  });
  const unlinkMutation = useMutation({
    mutationFn: (tagId: TagId) => api.unlinkCampaignGlobalTag(campaign.id, tagId),
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['campaign-global-tags', campaign.id] });
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось отвязать тег');
    },
  });

  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold">Глобальные теги домена</h4>
      <div className="mb-3 flex flex-wrap items-center gap-1">
        {linked.length === 0 ? (
          <span className="text-xs text-text-muted">Нет подключённых тегов</span>
        ) : (
          linked.map((t) => (
            <button
              key={t.id}
              type="button"
              className="group inline-flex items-center rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs font-medium hover:border-danger"
              onClick={() => unlinkMutation.mutate(t.id)}
              aria-label={`Отвязать тег ${t.name}`}
            >
              <span style={t.color ? { color: t.color } : undefined}>{t.name}</span>
              <span className="ml-1 text-text-muted group-hover:text-danger">×</span>
            </button>
          ))
        )}
      </div>

      {available.length > 0 && (
        <SelectWrapper label="Добавить глобальный тег">
          <Select
            value=""
            onChange={(e) => {
              const tid = e.target.value;
              if (tid) linkMutation.mutate(tid);
              e.target.value = '';
            }}
            options={[{ value: '', label: '+ Добавить глобальный тег…' }, ...available.map((t) => ({ value: t.id, label: t.name }))]}
          />
        </SelectWrapper>
      )}

      {error && (
        <div className="mt-2 rounded border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}
    </div>
  );
}

interface CampaignStateFieldsSectionProps {
  campaignId: CampaignId;
}

function CampaignStateFieldsSection({ campaignId }: CampaignStateFieldsSectionProps) {
  const fields = useStateFields(campaignId);
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [editingField, setEditingField] = useState<{
    field_id: string;
    key: string;
    label: string;
    mode: StateFieldMode;
    enabled: boolean;
    display_order: number;
  } | null>(null);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-sm font-semibold">Поля Campaign State</h4>
        <Button size="sm" variant="ghost" onClick={() => setAdding(true)}>
          + Поле
        </Button>
      </div>
      {fields.loading ? (
        <p className="text-xs text-text-muted">Загрузка…</p>
      ) : fields.list.length === 0 ? (
        <p className="text-xs text-text-muted">Нет настроенных полей</p>
      ) : (
        <ul className="space-y-1">
          {fields.list.map((f) => (
            <li
              key={f.field_id}
              className="flex items-center justify-between rounded border border-border p-2 text-sm"
            >
              <div>
                <code className="text-xs">{f.key}</code> · {f.label}
                <span className="ml-2 text-xs text-text-muted">({f.mode})</span>
              </div>
              <div className="flex gap-2">
                <Checkbox
                  checked={f.enabled}
                  onChange={() => fields.toggleEnabled(f.field_id, !f.enabled)}
                />
                <Button size="sm" onClick={() => setEditingField(f)}>
                  Редактировать
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => fields.remove(f.field_id)}
                >
                  Удалить
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {adding && (
        <AddFieldInline
          onSubmit={(data) => {
            fields.create(data);
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      )}
      {editingField && (
        <EditFieldValueDialog
          open
          campaignId={campaignId}
          field={editingField}
          onClose={() => setEditingField(null)}
          onSaved={() => {
            void queryClient.invalidateQueries({ queryKey: ['active-state', campaignId] });
            void queryClient.invalidateQueries({ queryKey: ['effective-context', campaignId] });
            setEditingField(null);
          }}
        />
      )}
    </div>
  );
}

interface AddFieldInlineProps {
  onSubmit: (data: CreateStateFieldRequest) => void;
  onCancel: () => void;
}

function AddFieldInline({ onSubmit, onCancel }: AddFieldInlineProps) {
  const [key, setKey] = useState('');
  const [label, setLabel] = useState('');
  const [mode, setMode] = useState<StateFieldMode>('single');

  return (
    <div className="mt-2 flex flex-wrap items-end gap-2 rounded border border-border p-2">
      <Field label="Ключ:" className="flex-1">
        <Input
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="current_location"
        />
      </Field>
      <Field label="Название:" className="flex-1">
        <Input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Текущая локация"
        />
      </Field>
      <Field label="Режим:">
        <SelectWrapper>
          <Select
            value={mode}
            onChange={(e) => setMode(e.target.value as StateFieldMode)}
            options={[
              { value: 'single', label: 'Single' },
              { value: 'list', label: 'List' },
            ]}
          />
        </SelectWrapper>
      </Field>
      <div className="flex gap-1">
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Отмена
        </Button>
        <Button
          size="sm"
          disabled={!key || !label}
          onClick={() => onSubmit({ key, label, mode, enabled: true })}
        >
          Добавить
        </Button>
      </div>
    </div>
  );
}