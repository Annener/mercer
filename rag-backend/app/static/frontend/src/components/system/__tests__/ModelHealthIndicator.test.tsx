import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ModelHealthIndicator } from '../ModelHealthIndicator';
import type {
  EmbeddingModel,
  GenerationModel,
  PlatformStatus,
  RerankModel,
} from '@/api/types';

const settingsStoreState: { openSettings: ReturnType<typeof vi.fn> } = {
  openSettings: vi.fn(),
};

vi.mock('@/stores', () => ({
  useSettingsStore: (selector: (s: typeof settingsStoreState) => unknown) =>
    selector(settingsStoreState),
}));

vi.mock('@/api/client', () => ({
  api: {
    getSettingsStatus: vi.fn(),
    getGenerationModels: vi.fn(),
    getEmbeddingModels: vi.fn(),
    getRerankModels: vi.fn(),
    getModelHealth: vi.fn(),
    sidecarStart: vi.fn(),
    sidecarStop: vi.fn(),
  },
}));

import { api } from '@/api/client';

function renderWithQueryClient(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const STATUS_ALL_OK: PlatformStatus = {
  has_active_generation_model: true,
  has_active_embedding_model: true,
  pdf_sidecar_available: true,
  has_vaults: true,
};

const STATUS_NO_SIDECAR: PlatformStatus = {
  ...STATUS_ALL_OK,
  pdf_sidecar_available: false,
};

const GEN_MODEL: GenerationModel = {
  model_id: 'gen-1',
  display_name: 'Gen 1',
  provider: 'openai_compatible',
  is_active: true,
} as unknown as GenerationModel;

const EMB_MODEL: EmbeddingModel = {
  model_id: 'emb-1',
  display_name: 'Emb 1',
  provider: 'openai_compatible',
  enabled: true,
} as unknown as EmbeddingModel;

const RERANK_MODEL: RerankModel = {
  model_id: 'rerank-1',
  display_name: 'Rerank 1',
  provider: 'cohere',
  is_active: true,
} as unknown as RerankModel;

beforeEach(() => {
  vi.clearAllMocks();
  settingsStoreState.openSettings = vi.fn();
  vi.mocked(api.getModelHealth).mockResolvedValue({ status: 'ok', latency_ms: 120 });
  vi.mocked(api.sidecarStart).mockResolvedValue({ message: 'started' });
  vi.mocked(api.sidecarStop).mockResolvedValue({ message: 'stopped' });
});

describe('ModelHealthIndicator — кликабельность', () => {
  it('клик на generation открывает настройки на табе models', async () => {
    vi.mocked(api.getSettingsStatus).mockResolvedValue(STATUS_ALL_OK);
    vi.mocked(api.getGenerationModels).mockResolvedValue([GEN_MODEL]);

    renderWithQueryClient(<ModelHealthIndicator kind="generation" />);

    const btn = await screen.findByRole('button', { name: /Generation.*открыть настройки моделей/i });
    fireEvent.click(btn);

    expect(settingsStoreState.openSettings).toHaveBeenCalledWith('models');
  });

  it('клик на embedding открывает настройки на табе models', async () => {
    vi.mocked(api.getSettingsStatus).mockResolvedValue(STATUS_ALL_OK);
    vi.mocked(api.getEmbeddingModels).mockResolvedValue([EMB_MODEL]);

    renderWithQueryClient(<ModelHealthIndicator kind="embedding" />);

    const btn = await screen.findByRole('button', { name: /Embedding.*открыть настройки моделей/i });
    fireEvent.click(btn);

    expect(settingsStoreState.openSettings).toHaveBeenCalledWith('models');
  });

  it('клик на rerank открывает настройки на табе models', async () => {
    vi.mocked(api.getSettingsStatus).mockResolvedValue(STATUS_ALL_OK);
    vi.mocked(api.getRerankModels).mockResolvedValue([RERANK_MODEL]);

    renderWithQueryClient(<ModelHealthIndicator kind="rerank" />);

    const btn = await screen.findByRole('button', { name: /Reranker.*открыть настройки моделей/i });
    fireEvent.click(btn);

    expect(settingsStoreState.openSettings).toHaveBeenCalledWith('models');
  });

  it('клик на sidecar (доступен) вызывает sidecarStop', async () => {
    vi.mocked(api.getSettingsStatus).mockResolvedValue(STATUS_ALL_OK);

    renderWithQueryClient(<ModelHealthIndicator kind="sidecar" />);

    const btn = await screen.findByRole('button', { name: /Sidecar запущен — остановить/i });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(api.sidecarStop).toHaveBeenCalledTimes(1);
    });
    expect(api.sidecarStart).not.toHaveBeenCalled();
    expect(settingsStoreState.openSettings).not.toHaveBeenCalled();
  });

  it('клик на sidecar (недоступен) вызывает sidecarStart', async () => {
    vi.mocked(api.getSettingsStatus).mockResolvedValue(STATUS_NO_SIDECAR);

    renderWithQueryClient(<ModelHealthIndicator kind="sidecar" />);

    const btn = await screen.findByRole('button', { name: /Sidecar остановлен — запустить/i });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(api.sidecarStart).toHaveBeenCalledTimes(1);
    });
    expect(api.sidecarStop).not.toHaveBeenCalled();
    expect(settingsStoreState.openSettings).not.toHaveBeenCalled();
  });

  it('sidecar-индикатор заблокирован пока platform-status не загружен', async () => {
    let resolveStatus: (v: PlatformStatus) => void = () => {};
    vi.mocked(api.getSettingsStatus).mockImplementation(
      () => new Promise<PlatformStatus>((res) => { resolveStatus = res; }),
    );

    renderWithQueryClient(<ModelHealthIndicator kind="sidecar" />);

    const btn = await screen.findByRole('button', { name: /Sidecar.*состояние проверяется/i });
    expect(btn).toBeDisabled();

    fireEvent.click(btn);
    expect(api.sidecarStart).not.toHaveBeenCalled();
    expect(api.sidecarStop).not.toHaveBeenCalled();

    await act(async () => {
      resolveStatus(STATUS_ALL_OK);
    });
  });

  it('инвалидирует platform-status и sidecar-status после успешного stop', async () => {
    vi.mocked(api.getSettingsStatus).mockResolvedValue(STATUS_ALL_OK);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');

    render(
      <QueryClientProvider client={qc}>
        <ModelHealthIndicator kind="sidecar" />
      </QueryClientProvider>,
    );

    const btn = await screen.findByRole('button', { name: /Sidecar запущен — остановить/i });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['platform-status'] });
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['sidecar', 'status'] });
  });
});
