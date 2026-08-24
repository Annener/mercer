import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Badge,
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
import { useDomainStore, useSettingsStore } from '@/stores';
import type {
  Domain,
  DomainId,
  EmbeddingModel,
  Vault,
  VaultId,
} from '@/api/types';

const GIT_DEFAULT_NAME = 'Mercer';
const GIT_DEFAULT_EMAIL = 'mercer@local';

export function VaultsTab() {
  const selectedRailDomainId = useSettingsStore((s) => s.selectedRailDomainId);
  const [creating, setCreating] = useState(false);

  const vaultsQuery = useQuery({
    queryKey: ['vaults', selectedRailDomainId],
    queryFn: () => api.getVaults(selectedRailDomainId),
  });

  const vaults = vaultsQuery.data ?? [];
  const isAll = selectedRailDomainId === null;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setCreating(true)}>+ Vault</Button>
      </div>

      <CreateVaultModal
        open={creating}
        defaultDomainId={selectedRailDomainId}
        onClose={() => setCreating(false)}
        onCreated={() => {
          void vaultsQuery.refetch();
        }}
      />

      {vaultsQuery.isLoading ? (
        <p className="text-sm text-text-muted">Загрузка…</p>
      ) : vaults.length === 0 ? (
        <EmptyState
          title={isAll ? 'Нет хранилищ' : 'В этом домене нет хранилищ'}
          description="Создайте первое хранилище, чтобы начать индексировать документы"
          actions={
            <Button size="sm" onClick={() => setCreating(true)}>
              + Vault
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
          {vaults.map((v) => (
            <VaultCard
              key={v.vault_id}
              vault={v}
              showDomainBadge={isAll}
              onChanged={() => void vaultsQuery.refetch()}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface VaultCardProps {
  vault: Vault;
  showDomainBadge: boolean;
  onChanged: () => void;
}

function VaultCard({ vault, showDomainBadge, onChanged }: VaultCardProps) {
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const isEnabled = vault.enabled !== false;

  const toggleMutation = useMutation({
    mutationFn: () => api.toggleVault(vault.vault_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['vaults'] });
      onChanged();
    },
  });

  const badges = <StatusBadge kind={isEnabled ? 'active' : 'inactive'} />;

  const menu: SettingsCardMenuItem[] = [
    { key: 'edit', label: 'Изменить', onClick: () => setEditOpen(true) },
    {
      key: 'toggle',
      label: isEnabled ? 'Выключить' : 'Включить',
      disabled: toggleMutation.isPending,
      onClick: () => toggleMutation.mutate(),
    },
    {
      key: 'delete',
      label: 'Удалить',
      danger: true,
      onClick: () => {
        setDeleteOpen(true);
      },
    },
  ];

  return (
    <>
      <SettingsCard
        title={vault.display_name || vault.vault_id}
        badges={badges}
        subtitle={showDomainBadge ? undefined : vault.vault_id}
        meta={
          showDomainBadge ? (
            <span>
                <Badge variant="info">{vault.domain_id}</Badge>
                <span className="ml-2 font-mono text-xs text-text-muted">{vault.vault_id}</span>
              </span>
          ) : undefined
        }
        active={isEnabled}
        menu={menu}
      />

      <EditVaultModal
        open={editOpen}
        vault={vault}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          setEditOpen(false);
          void queryClient.invalidateQueries({ queryKey: ['vaults'] });
          onChanged();
        }}
      />

      <DeleteVaultModal
        open={deleteOpen}
        vault={vault}
        onClose={() => {
          setDeleteOpen(false);
        }}
        onDeleted={async () => {
          setDeleteOpen(false);
          await queryClient.invalidateQueries({ queryKey: ['vaults'] });
          onChanged();
        }}
      />
    </>
  );
}

interface DeleteVaultModalProps {
  open: boolean;
  vault: Vault;
  onClose: () => void;
  onDeleted: () => void | Promise<void>;
}

function DeleteVaultModal({ open, vault, onClose, onDeleted }: DeleteVaultModalProps) {
  const [error, setError] = useState<string | null>(null);
  const deleteMutation = useMutation({
    mutationFn: () => api.deleteVault(vault.vault_id),
    onSuccess: async () => {
      await onDeleted();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось удалить vault');
    },
  });
  return (
    <ConfirmModal
      open={open}
      title="Удалить vault"
      message={
        <>
          Удалить vault <span className="font-semibold">{vault.display_name || vault.vault_id}</span>?
          Все документы внутри будут удалены. Действие необратимо.
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

interface EditVaultModalProps {
  open: boolean;
  vault: Vault;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

function EditVaultModal({ open, vault, onClose, onSaved }: EditVaultModalProps) {
  const [displayName, setDisplayName] = useState(vault.display_name ?? '');
  const [domainId, setDomainId] = useState(vault.domain_id);
  const [embeddingModelId, setEmbeddingModelId] = useState<string>(vault.embedding_model_id ?? '');
  const [chunkSize, setChunkSize] = useState<number>(vault.chunk_size ?? 1600);
  const [overlap, setOverlap] = useState<number>(vault.overlap ?? 0);
  const [entityAwareMode, setEntityAwareMode] = useState<boolean>(vault.entity_aware_mode ?? false);
  const [gitAuthorName, setGitAuthorName] = useState<string>(vault.git_author_name ?? '');
  const [gitAuthorEmail, setGitAuthorEmail] = useState<string>(vault.git_author_email ?? '');
  const [error, setError] = useState<string | null>(null);

  const domainsQuery = useQuery({
    queryKey: ['settings-domains'],
    queryFn: () => api.getSettingsDomains(),
    enabled: open,
  });

  const embModelsQuery = useQuery({
    queryKey: ['models', 'embedding'],
    queryFn: () => api.getEmbeddingModels(),
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    setDisplayName(vault.display_name ?? '');
    setDomainId(vault.domain_id);
    setEmbeddingModelId(vault.embedding_model_id ?? '');
    setChunkSize(vault.chunk_size ?? 1600);
    setOverlap(vault.overlap ?? 0);
    setEntityAwareMode(vault.entity_aware_mode ?? false);
    setGitAuthorName(vault.git_author_name ?? '');
    setGitAuthorEmail(vault.git_author_email ?? '');
    setError(null);
  }, [open, vault]);

  const domainOptions = (domainsQuery.data ?? [])
    .filter((d) => d.domain_id !== 'default' && d.enabled !== false)
    .map((d) => ({ value: d.domain_id, label: d.display_name ?? d.domain_id }));

  const embModelOptions = (embModelsQuery.data ?? []).map((m) => ({
    value: m.model_id,
    label: m.display_name ?? m.model_id,
  }));

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateVault(vault.vault_id, {
        display_name: displayName.trim() || null,
        domain_id: domainId,
        embedding_model_id: embeddingModelId || null,
        chunk_size: chunkSize,
        overlap: overlap,
        entity_aware_mode: entityAwareMode,
        git_author_name: gitAuthorName.trim() || null,
        git_author_email: gitAuthorEmail.trim() || null,
      }),
    onSuccess: async () => {
      setError(null);
      await onSaved();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось сохранить vault');
    },
  });

  return (
    <Modal
      open={open}
      onClose={() => {
        if (saveMutation.isPending) return;
        onClose();
      }}
      title={`Изменить vault «${vault.display_name || vault.vault_id}»`}
      size="md"
    >
      <form
        className="space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          saveMutation.mutate();
        }}
      >
        <div>
          <span className="mb-1 block text-sm font-medium text-text">Slug (vault_id)</span>
          <Input value={vault.vault_id} disabled className="font-mono" />
          <span className="mt-1 block text-xs text-text-muted">
            Идентификатор нельзя изменить после создания.
          </span>
        </div>

        <Field label="Отображаемое имя">
          <Input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder={vault.vault_id}
          />
        </Field>

        <SelectWrapper label="Домен">
          <Select value={domainId} onChange={(e) => setDomainId(e.target.value)} options={domainOptions} />
        </SelectWrapper>

        <SelectWrapper label="Embedding-модель">
          <Select
            value={embeddingModelId}
            onChange={(e) => setEmbeddingModelId(e.target.value)}
            options={[{ value: '', label: '— не выбрана —' }, ...embModelOptions]}
          />
        </SelectWrapper>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Размер чанка">
            <Input
              type="number"
              value={chunkSize}
              min={64}
              onChange={(e) => setChunkSize(Number(e.target.value) || 0)}
            />
          </Field>
          <Field label="Overlap">
            <Input
              type="number"
              value={overlap}
              min={0}
              onChange={(e) => setOverlap(Number(e.target.value) || 0)}
            />
          </Field>
        </div>

        <Checkbox
          checked={entityAwareMode}
          onChange={(e) => setEntityAwareMode(e.target.checked)}
          label="Умный чанкинг (entity aware)"
        />

        <hr className="border-border" />

        <p className="text-xs text-text-muted">
          <strong>Git identity</strong> — имя автора и email для git-коммитов Campaign Update Mode.
          Пустые поля будут заменены значениями по умолчанию.
        </p>

        <Field label="Git Author Name">
          <Input
            value={gitAuthorName}
            onChange={(e) => setGitAuthorName(e.target.value)}
            placeholder={GIT_DEFAULT_NAME}
          />
        </Field>

        <Field label="Git Author Email">
          <Input
            type="email"
            value={gitAuthorEmail}
            onChange={(e) => setGitAuthorEmail(e.target.value)}
            placeholder={GIT_DEFAULT_EMAIL}
          />
        </Field>

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
          <Button type="submit" loading={saveMutation.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface CreateVaultModalProps {
  open: boolean;
  defaultDomainId: DomainId | null;
  onClose: () => void;
  onCreated: () => void;
}

function CreateVaultModal({ open, defaultDomainId, onClose, onCreated }: CreateVaultModalProps) {
  const domains = useDomainStore((s) => s.domains);
  const [vaultId, setVaultId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [domainId, setDomainId] = useState<string>(defaultDomainId ?? '');
  const [embeddingModelId, setEmbeddingModelId] = useState<string>('');
  const [chunkSize, setChunkSize] = useState<number>(1600);
  const [overlap, setOverlap] = useState<number>(0);
  const [entityAwareMode, setEntityAwareMode] = useState<boolean>(false);
  const [gitAuthorName, setGitAuthorName] = useState<string>(GIT_DEFAULT_NAME);
  const [gitAuthorEmail, setGitAuthorEmail] = useState<string>(GIT_DEFAULT_EMAIL);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setVaultId('');
    setDisplayName('');
    setDomainId(defaultDomainId ?? '');
    setEmbeddingModelId('');
    setChunkSize(1600);
    setOverlap(0);
    setEntityAwareMode(false);
    setGitAuthorName(GIT_DEFAULT_NAME);
    setGitAuthorEmail(GIT_DEFAULT_EMAIL);
    setError(null);
  }, [open, defaultDomainId]);

  const embModelsQuery = useQuery({
    queryKey: ['models', 'embedding'],
    queryFn: () => api.getEmbeddingModels(),
    enabled: open,
  });

  const domainOptions: Array<{ value: string; label: string }> = [
    ...domains
      .filter((d) => d.domain_id !== 'default' && d.enabled !== false)
      .map((d) => ({ value: d.domain_id, label: d.display_name ?? d.domain_id })),
  ];

  const embModelOptions: Array<{ value: string; label: string }> = (embModelsQuery.data ?? []).map(
    (m) => ({ value: m.model_id, label: m.display_name ?? m.model_id }),
  );

  const createMutation = useMutation({
    mutationFn: () =>
      api.createVault({
        vault_id: vaultId,
        domain_id: domainId,
        display_name: displayName.trim() || null,
        embedding_model_id: embeddingModelId || null,
        chunk_size: chunkSize,
        overlap: overlap,
        entity_aware_mode: entityAwareMode,
        git_author_name: gitAuthorName.trim() || GIT_DEFAULT_NAME,
        git_author_email: gitAuthorEmail.trim() || GIT_DEFAULT_EMAIL,
      }),
    onSuccess: async () => {
      setError(null);
      onClose();
      onCreated();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось создать vault');
    },
  });

  return (
    <Modal
      open={open}
      onClose={() => {
        if (createMutation.isPending) return;
        onClose();
      }}
      title="Новый vault"
      size="md"
    >
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

        <Field label="Slug (vault_id)">
          <Input
            value={vaultId}
            onChange={(e) => setVaultId(e.target.value)}
            placeholder="my-vault"
            className="font-mono"
          />
        </Field>
        <span className="-mt-2 block text-xs text-text-muted">
          Только латиница, цифры и дефис, от 3 до 64 символов.
        </span>

        <Field label="Отображаемое имя">
          <Input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="My Vault"
          />
        </Field>

        <SelectWrapper label="Embedding-модель">
          <Select
            value={embeddingModelId}
            onChange={(e) => setEmbeddingModelId(e.target.value)}
            options={[{ value: '', label: '— не выбрана —' }, ...embModelOptions]}
          />
        </SelectWrapper>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Размер чанка">
            <Input
              type="number"
              value={chunkSize}
              min={64}
              onChange={(e) => setChunkSize(Number(e.target.value) || 0)}
            />
          </Field>
          <Field label="Overlap">
            <Input
              type="number"
              value={overlap}
              min={0}
              onChange={(e) => setOverlap(Number(e.target.value) || 0)}
            />
          </Field>
        </div>

        <Checkbox
          checked={entityAwareMode}
          onChange={(e) => setEntityAwareMode(e.target.checked)}
          label="Умный чанкинг (entity aware)"
        />

        <hr className="border-border" />

        <Field label="Git Author Name">
          <Input value={gitAuthorName} onChange={(e) => setGitAuthorName(e.target.value)} />
        </Field>

        <Field label="Git Author Email">
          <Input
            type="email"
            value={gitAuthorEmail}
            onChange={(e) => setGitAuthorEmail(e.target.value)}
          />
        </Field>

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
            disabled={createMutation.isPending}
          >
            Отмена
          </Button>
          <Button
            type="submit"
            disabled={!vaultId || !domainId || createMutation.isPending}
            loading={createMutation.isPending}
          >
            Создать
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// Re-export so JSX usage compiles — note these are already imported above.
export type { Domain, EmbeddingModel, VaultId };