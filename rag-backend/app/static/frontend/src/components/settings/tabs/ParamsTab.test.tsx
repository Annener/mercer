import { describe, it, expect, vi } from 'vitest';
import type { ReactNode } from 'react';
import { act, screen, fireEvent, render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ParamsTab } from './ParamsTab';
import type { PlatformSetting } from '@/api/types';

vi.mock('@/api/client', () => ({
  api: {
    getSettingsParams: vi.fn(),
    updateSettingsParam: vi.fn(),
    resetSettingsParams: vi.fn(),
    getWatchdogSettings: vi.fn(),
    saveWatchdogSettings: vi.fn(),
    getSidecarStatus: vi.fn(),
    sidecarStart: vi.fn(),
    sidecarStop: vi.fn(),
    sidecarRestart: vi.fn(),
    getSidecarInstallStreamUrl: vi.fn(() => '/api/settings/sidecar/install/stream'),
  },
  HttpError: class HttpError extends Error {
    readonly status: number;
    constructor(status: number, _detail: unknown, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { api } from '@/api/client';

const SAMPLE_PARAMS: PlatformSetting[] = [
  {
    key: 'retrieval.enabled',
    value: true,
    value_type: 'bool',
    group_name: 'retrieval',
    label: 'RAG включён',
    hint: 'Поиск по базе знаний',
  },
  {
    key: 'retrieval.top_k',
    value: 20,
    value_type: 'int',
    group_name: 'retrieval',
    label: 'Top-K',
    hint: 'Глубина поиска',
  },
  {
    key: 'chat.stream_answers',
    value: true,
    value_type: 'bool',
    group_name: 'chat',
    label: 'Стриминг',
    hint: 'Стримить ответы',
  },
  {
    key: 'watchdog_auto_index_extensions',
    value: '.md,.pdf',
    value_type: 'str',
    group_name: 'indexing',
    label: 'Расширения',
    hint: '',
  },
];

function renderWithQuery(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('ParamsTab', () => {
  it('рендерит группы с человеко-читаемыми label из API', async () => {
    vi.mocked(api.getSettingsParams).mockResolvedValue(SAMPLE_PARAMS);
    vi.mocked(api.getWatchdogSettings).mockResolvedValue({
      auto_index_extensions: ['.md', '.pdf'],
      interval_sec: 60,
    });
    vi.mocked(api.getSidecarStatus).mockResolvedValue({
      running: false,
      installed: true,
    });

    renderWithQuery(<ParamsTab />);

    expect(await screen.findByText('Настройки чатов')).toBeInTheDocument();
    expect(screen.getByText('Настройки взаимодействия с RAG')).toBeInTheDocument();
    expect(screen.getByText('Vault Watchdog')).toBeInTheDocument();
    expect(screen.getByText('PDF Sidecar')).toBeInTheDocument();

    expect(screen.getByText('RAG включён')).toBeInTheDocument();
    expect(screen.getByText('Top-K')).toBeInTheDocument();
    expect(screen.getByText('Поиск по базе знаний')).toBeInTheDocument();

    // watchdog-managed ключ НЕ попадает в обычные параметры
    expect(screen.queryByText('Расширения')).not.toBeInTheDocument();
  });

  it('помечает форму как dirty и шлёт PUT только изменённых ключей', async () => {
    vi.mocked(api.getSettingsParams).mockResolvedValue(SAMPLE_PARAMS);
    vi.mocked(api.updateSettingsParam).mockResolvedValue({});
    vi.mocked(api.getWatchdogSettings).mockResolvedValue({
      auto_index_extensions: ['.md'],
      interval_sec: 60,
    });
    vi.mocked(api.getSidecarStatus).mockResolvedValue({
      running: false,
      installed: true,
    });

    renderWithQuery(<ParamsTab />);

    const topKInput = await screen.findByLabelText('Top-K');
    await act(async () => {
      fireEvent.change(topKInput, { target: { value: '42' } });
    });

    const saveButton = screen.getAllByRole('button', { name: /Сохранить/ }).pop();
    expect(saveButton).toBeDefined();
    expect(saveButton).not.toBeDisabled();

    await act(async () => {
      saveButton?.click();
    });

    await waitFor(() => {
      expect(api.updateSettingsParam).toHaveBeenCalledWith('retrieval.top_k', 42);
    });
    const calls = vi.mocked(api.updateSettingsParam).mock.calls;
    const keys = calls.map((c) => c[0]);
    expect(keys).toEqual(['retrieval.top_k']);
  });
});