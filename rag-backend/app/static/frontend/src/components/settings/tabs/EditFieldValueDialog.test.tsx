import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EditFieldValueDialog } from './EditFieldValueDialog';
import type {
  CampaignStatePatchResponse,
  CampaignStateVersion,
} from '@/api/types';

vi.mock('@/api/client', () => ({
  api: {
    getActiveCampaignState: vi.fn(),
    patchCampaignState: vi.fn(),
  },
  HttpError: class HttpError extends Error {
    readonly status: number;
    readonly detail: unknown;
    constructor(status: number, detail: unknown, message: string) {
      super(message);
      this.status = status;
      this.detail = detail;
    }
    isCode(_code: string): boolean {
      return false;
    }
  },
}));

vi.mock('./InitialStateButton', () => ({
  InitialStateButton: () => <button>Initial State</button>,
}));

import { api } from '@/api/client';

const CAMPAIGN = 'camp-1';
const SINGLE_FIELD = {
  field_id: 'fld-1',
  key: 'current_focus',
  label: 'Текущий фокус',
  mode: 'single' as const,
  enabled: true,
  display_order: 0,
};

const LIST_FIELD = {
  field_id: 'fld-2',
  key: 'npcs',
  label: 'NPC',
  mode: 'list' as const,
  enabled: true,
  display_order: 1,
};

const SINGLE_STATE: CampaignStateVersion = {
  summary: {
    id: 'ver-2',
    campaign_id: CAMPAIGN,
    state_version: 2,
    config_version: 1,
    source_kind: 'initial',
  },
  fields: [
    {
      field_key: 'current_focus',
      field_id: 'fld-1',
      mode: 'single',
      enabled: true,
      display_order: 0,
      single_value: { field_key: 'current_focus', text: 'Бой с боссом', source_refs: [] },
      items: [],
    },
  ],
};

const LIST_STATE: CampaignStateVersion = {
  summary: {
    id: 'ver-3',
    campaign_id: CAMPAIGN,
    state_version: 3,
    config_version: 1,
    source_kind: 'initial',
  },
  fields: [
    {
      field_key: 'npcs',
      field_id: 'fld-2',
      mode: 'list',
      enabled: true,
      display_order: 0,
      single_value: null,
      items: [
        { field_key: 'npcs', item_key: 'item-1', text: 'Бехолдер', resolved: false, source_refs: [] },
      ],
    },
  ],
};

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = 'TestQueryWrapper';
  return Wrapper;
}

const OK_RESPONSE: CampaignStatePatchResponse = {
  applied_state_version: 3,
  config_version: 1,
  applied_operations: [],
  failed_operations: [],
};

describe('EditFieldValueDialog — single', () => {
  beforeEach(() => {
    vi.mocked(api.patchCampaignState).mockReset();
    vi.mocked(api.getActiveCampaignState).mockReset();
  });

  it('single: редактирование текста → один patch с replace_single', async () => {
    vi.mocked(api.getActiveCampaignState).mockResolvedValue(SINGLE_STATE);
    vi.mocked(api.patchCampaignState).mockResolvedValue({
      ...OK_RESPONSE,
      applied_operations: ['replace_single'],
    });

    render(
      <EditFieldValueDialog
        open
        campaignId={CAMPAIGN}
        field={SINGLE_FIELD}
        onClose={() => {}}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    );

    const textarea = (await screen.findByLabelText('Текущее значение')) as HTMLTextAreaElement;
    expect(textarea.value).toBe('Бой с боссом');

    fireEvent.change(textarea, { target: { value: 'Новый фокус' } });

    fireEvent.click(screen.getByRole('button', { name: /^Сохранить$/ }));

    await waitFor(() => {
      expect(api.patchCampaignState).toHaveBeenCalledTimes(1);
    });

    expect(api.patchCampaignState).toHaveBeenCalledWith(CAMPAIGN, {
      base_state_version: 2,
      config_version: 1,
      operations: [
        {
          type: 'replace_single',
          field_key: 'current_focus',
          text: 'Новый фокус',
          reason: 'manual edit from settings',
        },
      ],
    });
  });
});

describe('EditFieldValueDialog — list', () => {
  beforeEach(() => {
    vi.mocked(api.patchCampaignState).mockReset();
    vi.mocked(api.getActiveCampaignState).mockReset();
  });

  it('list: добавление и удаление → один batch-вызов с add_list_item + remove_list_item', async () => {
    vi.mocked(api.getActiveCampaignState).mockResolvedValue(LIST_STATE);
    vi.mocked(api.patchCampaignState).mockResolvedValue({
      ...OK_RESPONSE,
      applied_operations: ['add_list_item', 'remove_list_item'],
    });

    render(
      <EditFieldValueDialog
        open
        campaignId={CAMPAIGN}
        field={LIST_FIELD}
        onClose={() => {}}
        onSaved={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    );

    // ждём, пока элемент item-1 появится
    await screen.findByText('item-1');

    // удаляем существующий элемент: первая "Удалить" в строке списка
    const allDeleteBtns = screen.getAllByRole('button', { name: 'Удалить' });
    expect(allDeleteBtns.length).toBeGreaterThanOrEqual(1);
    fireEvent.click(allDeleteBtns[0]!); // открывает ConfirmModal

    // подтверждаем: теперь на экране 3 кнопки "Удалить" (row + Cancel + Confirm в ConfirmModal)
    const allDeleteBtnsAfter = screen.getAllByRole('button', { name: 'Удалить' });
    fireEvent.click(allDeleteBtnsAfter[allDeleteBtnsAfter.length - 1]!);

    // добавляем новый
    const newInput = screen.getByPlaceholderText('Текст нового элемента');
    fireEvent.change(newInput, { target: { value: 'Культист' } });
    fireEvent.click(screen.getByRole('button', { name: /\+ Добавить/ }));

    fireEvent.click(screen.getByRole('button', { name: /Сохранить всё/ }));

    await waitFor(() => {
      expect(api.patchCampaignState).toHaveBeenCalledTimes(1);
    });

    const [, body] = vi.mocked(api.patchCampaignState).mock.calls[0]!;
    expect(body).toMatchObject({
      base_state_version: 3,
      config_version: 1,
    });
    expect(body.operations).toHaveLength(2);
    expect(body.operations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ type: 'remove_list_item', field_key: 'npcs', item_key: 'item-1' }),
        expect.objectContaining({ type: 'add_list_item', field_key: 'npcs', text: 'Культист' }),
      ]),
    );
    for (const op of body.operations) {
      expect(op.reason).toBe('manual edit from settings');
    }
  });
});