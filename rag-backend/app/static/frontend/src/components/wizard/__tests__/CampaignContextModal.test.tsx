import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CampaignContextModal } from '../CampaignContextModal';
import type { CampaignStateVersion } from '@/api/types';

vi.mock('@/api/client', () => ({
  api: {
    getCampaign: vi.fn(),
    getActiveCampaignState: vi.fn(),
  },
  HttpError: class HttpError extends Error {
    readonly status: number;
    readonly detail: unknown;
    constructor(status: number, _detail: unknown, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { api } from '@/api/client';

function renderWithQueryClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

const SINGLE_STATE: CampaignStateVersion = {
  summary: {
    id: 'ver-1',
    campaign_id: 'camp-1',
    state_version: 1,
    config_version: 1,
    source_kind: 'initial',
    created_at: '2026-01-01T00:00:00Z',
  },
  fields: [
    {
      field_key: 'location',
      field_id: 'fld-1',
      field_label: 'Текущая локация',
      mode: 'single',
      enabled: true,
      display_order: 1,
      single_value: {
        field_key: 'location',
        text: 'Таверна "Красный дракон"',
        source_refs: ['file:doc-1'],
      },
    },
  ],
};

describe('CampaignContextModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('не рендерит модал когда campaignId=null', async () => {
    vi.mocked(api.getActiveCampaignState).mockResolvedValue(SINGLE_STATE);
    vi.mocked(api.getCampaign).mockResolvedValue({
      id: 'camp-1',
      name: 'Тестовая кампания',
      domain_id: 'dnd',
    });
    renderWithQueryClient(
      <CampaignContextModal campaignId={null} onClose={vi.fn()} />,
    );
    // Когда campaignId=null, modal open=false, ничего не показывается.
    expect(screen.queryByText(/Контекст:/i)).not.toBeInTheDocument();
  });

  it('рендерит empty-state когда state=null', async () => {
    vi.mocked(api.getCampaign).mockResolvedValue({
      id: 'camp-1',
      name: 'Без state',
      domain_id: 'dnd',
    });
    vi.mocked(api.getActiveCampaignState).mockResolvedValue(null);

    renderWithQueryClient(
      <CampaignContextModal campaignId="camp-1" onClose={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText(/не инициализирована/i)).toBeInTheDocument();
    });
  });

  it('рендерит поля single с заголовком и значением', async () => {
    vi.mocked(api.getCampaign).mockResolvedValue({
      id: 'camp-1',
      name: 'Кампания',
      domain_id: 'dnd',
    });
    vi.mocked(api.getActiveCampaignState).mockResolvedValue(SINGLE_STATE);

    renderWithQueryClient(
      <CampaignContextModal campaignId="camp-1" onClose={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText(/ТЕКУЩАЯ ЛОКАЦИЯ/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Таверна/i)).toBeInTheDocument();
    expect(screen.getByText(/1 ист\./i)).toBeInTheDocument();
  });

  it('рендерит list-поля с галочками для resolved', async () => {
    const listState: CampaignStateVersion = {
      summary: {
        id: 'ver-1',
        campaign_id: 'camp-1',
        state_version: 1,
        config_version: 1,
        source_kind: 'initial',
      },
      fields: [
        {
          field_key: 'quests',
          field_id: 'fld-2',
          field_label: 'Квесты',
          mode: 'list',
          enabled: true,
          display_order: 1,
          items: [
            {
              field_key: 'quests',
              item_key: 'q1',
              text: 'Найти меч',
              resolved: false,
              source_refs: [],
            },
            {
              field_key: 'quests',
              item_key: 'q2',
              text: 'Победить дракона',
              resolved: true,
              source_refs: [],
            },
          ],
        },
      ],
    };
    vi.mocked(api.getCampaign).mockResolvedValue({
      id: 'camp-1',
      name: 'Кампания',
      domain_id: 'dnd',
    });
    vi.mocked(api.getActiveCampaignState).mockResolvedValue(listState);

    renderWithQueryClient(
      <CampaignContextModal campaignId="camp-1" onClose={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText(/КВЕСТЫ/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Найти меч/i)).toBeInTheDocument();
    expect(screen.getByText(/Победить дракона/i)).toBeInTheDocument();
    expect(screen.getByText('2 элементов')).toBeInTheDocument();
  });

  it('вызывает onClose при клике на backdrop', async () => {
    vi.mocked(api.getCampaign).mockResolvedValue({
      id: 'camp-1',
      name: 'Кампания',
      domain_id: 'dnd',
    });
    vi.mocked(api.getActiveCampaignState).mockResolvedValue(SINGLE_STATE);

    const onClose = vi.fn();
    renderWithQueryClient(
      <CampaignContextModal campaignId="camp-1" onClose={onClose} />,
    );

    await waitFor(() => {
      expect(screen.getByText(/ТЕКУЩАЯ ЛОКАЦИЯ/i)).toBeInTheDocument();
    });

    // Backdrop — первый fixed inset-0 элемент в Modal.
    // Используем классы для поиска.
    const backdrop = document.querySelector('.fixed.inset-0');
    expect(backdrop).toBeTruthy();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalled();
  });
});
