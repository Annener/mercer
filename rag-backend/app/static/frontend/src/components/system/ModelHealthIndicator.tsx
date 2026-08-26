import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { clsx } from '@/components/ui';
import { api } from '@/api/client';
import { useSettingsStore } from '@/stores';
import type {
  EmbeddingModel,
  GenerationModel,
  ModelHealthState,
  PlatformStatus,
  RerankModel,
} from '@/api/types';

export type HealthKind = 'generation' | 'embedding' | 'rerank' | 'sidecar';

const KIND_LABELS: Record<HealthKind, string> = {
  generation: 'Generation',
  embedding: 'Embedding',
  rerank: 'Reranker',
  sidecar: 'Sidecar',
};

const REFRESH_MS = 60_000;

interface ModelHealthIndicatorProps {
  kind: HealthKind;
}

type StatusKey = 'ok' | 'fail' | 'unchecked' | 'hidden';

const COLOR_MAP: Record<StatusKey, { dot: string; text: string }> = {
  ok: { dot: 'bg-success', text: 'text-success' },
  fail: { dot: 'bg-danger', text: 'text-danger' },
  unchecked: { dot: 'bg-text-muted/40', text: 'text-text-muted' },
  hidden: { dot: 'bg-text-muted/40', text: 'text-text-muted' },
};

interface AvailabilityInfo {
  hidden: boolean;
  statusKey: StatusKey;
  latencyText: string;
  tooltip: string;
}

function formatLatency(latencyMs: number): string {
  return `${(latencyMs / 1000).toFixed(1)}s`;
}

export function ModelHealthIndicator({ kind }: ModelHealthIndicatorProps) {
  const openSettings = useSettingsStore((s) => s.openSettings);
  const queryClient = useQueryClient();

  const listKind: 'generation' | 'embedding' | 'rerank' | null =
    kind === 'sidecar' ? null : kind;

  const statusQuery = useQuery<PlatformStatus>({
    queryKey: ['platform-status'],
    queryFn: () => api.getSettingsStatus(),
    refetchInterval: REFRESH_MS,
    refetchOnMount: true,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (statusQuery.data) {
      console.debug('[health] platform-status', statusQuery.data, new Date().toISOString());
    }
  }, [statusQuery.data]);

  const modelsQuery = useQuery<GenerationModel[] | EmbeddingModel[] | RerankModel[]>({
    queryKey: ['models', listKind],
    queryFn: () => {
      if (listKind === 'generation') return api.getGenerationModels();
      if (listKind === 'embedding') return api.getEmbeddingModels();
      if (listKind === 'rerank') return api.getRerankModels();
      return Promise.resolve([] as GenerationModel[]);
    },
    enabled: listKind !== null,
    staleTime: 30_000,
  });

  const targetModelId = pickTargetModelId(kind, modelsQuery.data);

  const healthQuery = useQuery<ModelHealthState>({
    queryKey: ['model-health', listKind, targetModelId],
    queryFn: () => {
      if (!listKind || !targetModelId) {
        return Promise.resolve({ status: 'unchecked' as const });
      }
      return api.getModelHealth(listKind, targetModelId);
    },
    enabled: listKind !== null && !!targetModelId,
    retry: 0,
    staleTime: 30_000,
  });

  const availability = resolveAvailability({
    kind,
    status: statusQuery.data,
    targetModelId,
    health: healthQuery.data,
    healthPending: healthQuery.isLoading || healthQuery.isFetching,
  });

  const sidecarStart = useMutation({
    mutationFn: () => api.sidecarStart(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
      void queryClient.invalidateQueries({ queryKey: ['sidecar', 'status'] });
    },
  });

  const sidecarStop = useMutation({
    mutationFn: () => api.sidecarStop(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
      void queryClient.invalidateQueries({ queryKey: ['sidecar', 'status'] });
    },
  });

  const isSidecar = kind === 'sidecar';
  const sidecarPending = sidecarStart.isPending || sidecarStop.isPending;
  const sidecarAvailable = statusQuery.data?.pdf_sidecar_available === true;
  const sidecarAction = isSidecar && statusQuery.data != null ? (
    sidecarAvailable ? sidecarStop : sidecarStart
  ) : null;

  const ariaLabel = (() => {
    if (isSidecar) {
      if (statusQuery.data == null) {
        return `${KIND_LABELS[kind]}: состояние проверяется`;
      }
      return sidecarAvailable
        ? `${KIND_LABELS[kind]} запущен — остановить`
        : `${KIND_LABELS[kind]} остановлен — запустить`;
    }
    return `${KIND_LABELS[kind]}: открыть настройки моделей`;
  })();

  const actionTooltip = (() => {
    if (isSidecar) {
      if (statusQuery.data == null) return availability.tooltip;
      return sidecarAvailable
        ? 'Остановить PDF sidecar'
        : 'Запустить PDF sidecar';
    }
    return availability.tooltip || 'Открыть настройки → Модели';
  })();

  const handleClick = () => {
    if (sidecarPending) return;
    if (sidecarAction) {
      sidecarAction.mutate();
      return;
    }
    openSettings('models');
  };

  const disabled = isSidecar && statusQuery.data == null;

  if (availability.hidden) return null;

  const color = COLOR_MAP[availability.statusKey];
  const dotClass = clsx(
    'inline-block h-2 w-2 rounded-full',
    sidecarPending ? 'animate-pulse bg-text-muted' : color.dot,
  );

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      title={actionTooltip}
      aria-label={ariaLabel}
      aria-busy={sidecarPending || undefined}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2 py-0.5 text-xs text-text transition',
        'hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary',
        'disabled:cursor-not-allowed disabled:opacity-60',
        'cursor-pointer',
      )}
      data-health-kind={kind}
      data-health-status={availability.statusKey}
    >
      <span className={dotClass} aria-hidden="true" />
      <span className="font-medium">{KIND_LABELS[kind]}</span>
      {availability.latencyText && (
        <span className="text-text-muted">· {availability.latencyText}</span>
      )}
      {sidecarPending && (
        <span
          aria-hidden="true"
          className="inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-text-muted border-t-transparent"
        />
      )}
    </button>
  );
}

function pickTargetModelId(
  kind: HealthKind,
  list: GenerationModel[] | EmbeddingModel[] | RerankModel[] | undefined,
): string | null {
  if (!list || list.length === 0) return null;

  if (kind === 'generation' || kind === 'rerank') {
    const found = list.find((m) => 'is_active' in m && (m as { is_active?: boolean }).is_active);
    if (found) return (found as { model_id: string }).model_id;
    return list[0] ? (list[0] as { model_id: string }).model_id : null;
  }

  if (kind === 'embedding') {
    const enabled = list.find((m) => (m as EmbeddingModel).enabled !== false);
    if (enabled) return (enabled as { model_id: string }).model_id;
    return null;
  }

  return null;
}

interface ResolveInput {
  kind: HealthKind;
  status: PlatformStatus | undefined;
  targetModelId: string | null;
  health: ModelHealthState | undefined;
  healthPending: boolean;
}

function resolveAvailability(input: ResolveInput): AvailabilityInfo {
  const { kind, status, targetModelId, health, healthPending } = input;

  if (kind === 'sidecar') {
    if (!status) {
      return {
        hidden: false,
        statusKey: 'unchecked',
        latencyText: '',
        tooltip: 'Состояние PDF sidecar проверяется',
      };
    }
    if (status.pdf_sidecar_available) {
      return {
        hidden: false,
        statusKey: 'ok',
        latencyText: 'доступен',
        tooltip: 'PDF sidecar доступен',
      };
    }
    return {
      hidden: false,
      statusKey: 'fail',
      latencyText: 'недоступен',
      tooltip: 'PDF sidecar недоступен — запуск парсинга/эмбеддинга может упасть',
    };
  }

  if (!status) {
    return { hidden: true, statusKey: 'hidden', latencyText: '', tooltip: '' };
  }

  if (!targetModelId) {
    return {
      hidden: false,
      statusKey: 'fail',
      latencyText: '',
      tooltip:
        kind === 'generation'
          ? 'Активная генеративная модель не выбрана. Откройте Настройки → Модели.'
          : kind === 'embedding'
          ? 'Нет включённой embedding-модели. Откройте Настройки → Модели.'
          : 'Активная rerank-модель не выбрана. Откройте Настройки → Модели.',
    };
  }

  if (healthPending && !health) {
    return {
      hidden: false,
      statusKey: 'unchecked',
      latencyText: '',
      tooltip: `Проверяется доступность модели ${targetModelId}`,
    };
  }

  const data: ModelHealthState = health ?? { status: 'unchecked' };

  if (data.status === 'ok') {
    const latencyMs = data.latency_ms;
    const showLatency = typeof latencyMs === 'number' && latencyMs > 0;
    return {
      hidden: false,
      statusKey: 'ok',
      latencyText: showLatency ? formatLatency(latencyMs as number) : '',
      tooltip: showLatency
        ? `${targetModelId} доступна (${latencyMs} мс)`
        : `${targetModelId} доступна`,
    };
  }
  if (data.status === 'fail') {
    return {
      hidden: false,
      statusKey: 'fail',
      latencyText: '',
      tooltip: data.error ? `${targetModelId}: ${data.error}` : `${targetModelId} недоступна`,
    };
  }
  return {
    hidden: false,
    statusKey: 'unchecked',
    latencyText: '',
    tooltip: `${targetModelId} ещё не проверена`,
  };
}
