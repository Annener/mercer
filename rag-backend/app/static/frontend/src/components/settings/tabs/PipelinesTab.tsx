import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Badge,
  Button,
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
import { PipelineBuilder } from './PipelineBuilder';
import type { DomainId, Pipeline, PipelineId } from '@/api/types';

export function PipelinesTab() {
  const selectedRailDomainId = useSettingsStore((s) => s.selectedRailDomainId);
  const [editing, setEditing] = useState<Pipeline | null>(null);
  const [creating, setCreating] = useState(false);

  const pipelinesQuery = useQuery({
    queryKey: ['pipelines', selectedRailDomainId],
    queryFn: () => api.getPipelines(selectedRailDomainId),
  });

  const isAll = selectedRailDomainId === null;
  const pipelines = pipelinesQuery.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setCreating(true)}>+ Новый pipeline</Button>
      </div>

      <CreatePipelineModal
        open={creating}
        defaultDomainId={selectedRailDomainId}
        onClose={() => setCreating(false)}
        onCreated={(p) => {
          setCreating(false);
          setEditing(p);
        }}
      />

      {editing && (
        <PipelineBuilder pipeline={editing} onClose={() => setEditing(null)} />
      )}

      {!editing && (
        <>
          {pipelinesQuery.isLoading ? (
            <p className="text-sm text-text-muted">Загрузка…</p>
          ) : pipelines.length === 0 ? (
            <EmptyState
              title={isAll ? 'Нет pipelines' : 'В этом домене нет pipelines'}
              description="Создайте первый pipeline, чтобы настроить обработку запросов"
              actions={
                <Button size="sm" onClick={() => setCreating(true)}>
                  + Новый pipeline
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
              {pipelines.map((p) => (
                <PipelineCard
                  key={p.pipeline_id}
                  pipeline={p}
                  showDomainBadge={isAll}
                  onChanged={() => void pipelinesQuery.refetch()}
                  onEdit={() => setEditing(p)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface PipelineCardProps {
  pipeline: Pipeline;
  showDomainBadge: boolean;
  onChanged: () => void;
  onEdit: () => void;
}

function PipelineCard({ pipeline, showDomainBadge, onChanged, onEdit }: PipelineCardProps) {
  const [deleteOpen, setDeleteOpen] = useState(false);
  const isActive = !!pipeline.is_active;

  const refId = pipeline.id ?? pipeline.pipeline_id;

  const activateMutation = useMutation({
    mutationFn: () => api.activatePipeline(refId),
    onSuccess: onChanged,
  });
  const deactivateMutation = useMutation({
    mutationFn: () => api.deactivatePipeline(refId),
    onSuccess: onChanged,
  });

  const badges = <StatusBadge kind={isActive ? 'active' : 'inactive'} />;

  const menu: SettingsCardMenuItem[] = [
    { key: 'edit', label: 'Редактировать', onClick: onEdit },
  ];
  if (isActive) {
    menu.push({
      key: 'deactivate',
      label: 'Деактивировать',
      disabled: deactivateMutation.isPending,
      onClick: () => deactivateMutation.mutate(),
    });
  } else {
    menu.push({
      key: 'activate',
      label: 'Активировать',
      disabled: activateMutation.isPending,
      onClick: () => activateMutation.mutate(),
    });
  }
  menu.push({
    key: 'delete',
    label: 'Удалить',
    danger: true,
    onClick: () => setDeleteOpen(true),
  });

  return (
    <>
      <SettingsCard
        title={pipeline.name}
        badges={badges}
        subtitle={pipeline.pipeline_id}
        meta={
          showDomainBadge && pipeline.domain_id ? (
            <Badge variant="info">{pipeline.domain_id}</Badge>
          ) : undefined
        }
        active={isActive}
        menu={menu}
      />

      <DeletePipelineModal
        open={deleteOpen}
        pipeline={pipeline}
        refId={refId}
        onClose={() => setDeleteOpen(false)}
        onDeleted={onChanged}
      />
    </>
  );
}

interface DeletePipelineModalProps {
  open: boolean;
  pipeline: Pipeline;
  refId: string;
  onClose: () => void;
  onDeleted: () => void;
}

function DeletePipelineModal({ open, pipeline, refId, onClose, onDeleted }: DeletePipelineModalProps) {
  const [error, setError] = useState<string | null>(null);
  const deleteMutation = useMutation({
    mutationFn: () => api.deletePipeline(refId),
    onSuccess: () => {
      setError(null);
      onClose();
      onDeleted();
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось удалить pipeline');
    },
  });

  return (
    <ConfirmModal
      open={open}
      title="Удалить pipeline"
      message={
        <>
          Удалить pipeline <span className="font-semibold">{pipeline.name}</span>? Действие необратимо.
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

interface CreatePipelineModalProps {
  open: boolean;
  defaultDomainId: DomainId | null;
  onClose: () => void;
  onCreated: (p: Pipeline) => void;
}

function CreatePipelineModal({ open, defaultDomainId, onClose, onCreated }: CreatePipelineModalProps) {
  const domains = useDomainStore((s) => s.domains);
  const [pipelineId, setPipelineId] = useState('');
  const [name, setName] = useState('');
  const [domainId, setDomainId] = useState<string>(defaultDomainId ?? '');
  const [error, setError] = useState<string | null>(null);

  // Reset on open
  useState(() => {
    if (open) {
      setPipelineId('');
      setName('');
      setDomainId(defaultDomainId ?? '');
      setError(null);
    }
    return null;
  });

  const domainOptions: Array<{ value: string; label: string }> = domains
    .filter((d) => d.domain_id !== 'default' && d.enabled !== false)
    .map((d) => ({ value: d.domain_id, label: d.display_name ?? d.domain_id }));

  const createMutation = useMutation({
    mutationFn: () =>
      api.createPipeline({
        pipeline_id: pipelineId,
        domain_id: domainId,
        name: name.trim() || pipelineId,
        steps: [],
        final_composition: 'concatenate',
      }),
    onSuccess: (p) => {
      setError(null);
      onCreated(p);
    },
    onError: (err) => {
      setError(err instanceof HttpError ? err.message : 'Не удалось создать pipeline');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Новый pipeline" size="md">
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

        <Field label="ID pipeline">
          <Input
            value={pipelineId}
            onChange={(e) => setPipelineId(e.target.value)}
            placeholder="my_pipeline"
            className="font-mono"
          />
        </Field>

        <Field label="Название">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={pipelineId || 'Мой pipeline'} />
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
            disabled={!pipelineId || !domainId || createMutation.isPending}
            loading={createMutation.isPending}
          >
            Создать
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// re-export
export type { PipelineId };