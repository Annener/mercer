import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { InitialStateButton } from './InitialStateButton';
import type {
  Document,
  InitialProposalRead,
  InitialProposalReadV2,
  TagRead,
} from '@/api/types';
import { HttpError } from '@/api/http';

function makeHttpError(status: number, detail: unknown): HttpError {
  return new HttpError(status, detail, 'fallback');
}

vi.mock('@/api/client', () => ({
  api: {
    getCampaign: vi.fn(),
    getCampaignTags: vi.fn(),
    getCampaignGlobalTags: vi.fn(),
    getSettingsDocuments: vi.fn(),
    getInitialStateProposal: vi.fn(),
    previewInitialState: vi.fn(),
    applyInitialState: vi.fn(),
  },
  HttpError: class HttpErrorMock extends Error {
    readonly status: number;
    readonly detail: unknown;
    constructor(status: number, detail: unknown, message: string) {
      super(message);
      this.status = status;
      this.detail = detail;
    }
    isCode(code: string): boolean {
      if (typeof this.detail === 'string') return this.detail === code;
      if (this.detail && typeof this.detail === 'object' && 'code' in this.detail) {
        return (this.detail as { code?: unknown }).code === code;
      }
      return false;
    }
  },
}));

import { api } from '@/api/client';

beforeEach(() => {
  vi.mocked(api.getCampaign).mockReset();
  vi.mocked(api.getCampaignTags).mockReset();
  vi.mocked(api.getCampaignGlobalTags).mockReset();
  vi.mocked(api.getSettingsDocuments).mockReset();
  vi.mocked(api.getInitialStateProposal).mockReset();
  vi.mocked(api.previewInitialState).mockReset();
  vi.mocked(api.applyInitialState).mockReset();
  // По умолчанию proposal отсутствует.
  vi.mocked(api.getInitialStateProposal).mockResolvedValue(null);
});

const TAG_OWN: TagRead = {
  id: 'tag-own',
  name: 'own',
  color: '#fff',
  domain_id: 'dom-1',
  campaign_id: 'camp-1',
};

const TAG_GLOBAL: TagRead = {
  id: 'tag-global',
  name: 'global',
  color: '#fff',
  domain_id: 'dom-1',
  campaign_id: null,
};

const DOCS: Document[] = [
  {
    id: 'doc-1',
    document_id: 'doc-1',
    title: 'lore.md',
    vault_id: 'v-1',
    source_path: '/vaults/work/lore.md',
    status: 'indexed',
    estimated_tokens: 4200,
  },
  {
    id: 'doc-2',
    document_id: 'doc-2',
    title: 'npcs.md',
    vault_id: 'v-1',
    source_path: '/vaults/work/npcs.md',
    status: 'indexed',
    estimated_tokens: 9800,
  },
  {
    id: 'doc-3',
    document_id: 'doc-3',
    title: 'huge.md',
    vault_id: 'v-1',
    source_path: '/vaults/work/huge.md',
    status: 'indexed',
    estimated_tokens: 99999, // превышает per-doc лимит
  },
];

function renderWithQuery(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

async function openWizard() {
  await act(async () => {
    screen.getByRole('button', { name: /Сформировать начальный контекст/i }).click();
  });
}

async function selectAll() {
  await waitFor(() => {
    expect(screen.getByText('lore.md')).toBeInTheDocument();
  });
  for (const d of DOCS) {
    if (d.estimated_tokens && d.estimated_tokens > 32000) continue;
    const cb = screen.getByRole('checkbox', { name: new RegExp(d.title!) });
    await act(async () => {
      cb.click();
    });
  }
}

function makeProposalRead(): InitialProposalReadV2 {
  return {
    proposal_id: 'prop-1',
    config_version: 1,
    source_snapshot: DOCS.filter(
      (d) => d.estimated_tokens && d.estimated_tokens <= 32000,
    ).map((d) => ({
      document_id: d.id,
      vault_id: d.vault_id,
      source_path: d.source_path ?? '',
      title: d.title ?? null,
      content_sha: 'a'.repeat(32),
      estimated_tokens: d.estimated_tokens ?? 0,
    })),
    proposal: {
      fields: [
        {
          field_key: 'goal',
          mode: 'single',
          status: 'proposed',
          single_value: {
            text: 'Найти артефакт',
            source_refs: [`file:doc-1:sha:${'a'.repeat(32)}`],
          },
          list_value: null,
        },
      ],
      suggested_fields: [
        {
          key: 'new_goal',
          label: 'Новая цель',
          description: 'Описание цели',
          mode: 'single',
          initial_status: 'proposed',
          single_value: { text: 'Найти меч', source_refs: [] },
          list_value: null,
        },
      ],
      questions: ['Какой у вас стиль повествования?'],
    },
    warnings: ['document_too_large_for_initial:doc-3'],
    created_at: '2026-08-25T10:00:00Z',
    expires_at: '2026-08-25T13:00:00Z',
  };
}

describe('InitialStateButton — восстановленные UI-фичи', () => {
  it('показывает степпер с тремя шагами', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();

    expect(screen.getByText('Документы')).toBeInTheDocument();
    expect(screen.getByText('Сводка')).toBeInTheDocument();
    expect(screen.getByText('Результат')).toBeInTheDocument();
  });

  it('отображает полные пути документов и точные estimated_tokens', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();

    await waitFor(() => {
      expect(screen.getByText('/vaults/work/lore.md')).toBeInTheDocument();
    });
    expect(screen.getByText('/vaults/work/npcs.md')).toBeInTheDocument();
    expect(screen.getAllByText(/4\s*200|9\s*800/).length).toBeGreaterThan(0);
  });

  it('дизаблит документы > 32k токенов и помечает их', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();

    await waitFor(() => {
      expect(screen.getByText(/слишком большой/i)).toBeInTheDocument();
    });
  });

  it('считает бюджет выбранных документов и показывает прогресс', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();
    await selectAll();

    await waitFor(() => {
      expect(screen.getByTestId('budget-selected').textContent).toMatch(/14\s?000/);
    });
    expect(screen.getByTestId('budget-fraction').textContent).toMatch(
      /14\s?000\s*\/\s*64\s?000/,
    );
  });

  it('показывает баннер ошибки с локализованным текстом и кодом при preview failure', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);
    vi.mocked(api.previewInitialState).mockRejectedValue(
      makeHttpError(503, { code: 'generation_provider_unavailable' }),
    );

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();
    await selectAll();
    await act(async () => {
      screen.getByTestId('next-button').click();
    });

    await waitFor(() => {
      expect(screen.getByText('Генеративная модель недоступна.')).toBeInTheDocument();
    });
    expect(screen.getByText(/code:\s*generation_provider_unavailable/)).toBeInTheDocument();
  });

  it('показывает inline-edit для single-поля и принимает изменения', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);
    vi.mocked(api.previewInitialState).mockResolvedValue(makeProposalRead());
    vi.mocked(api.applyInitialState).mockResolvedValue({
      summary: {
        id: 'v1',
        campaign_id: 'camp-1',
        state_version: 1,
        config_version: 1,
        source_kind: 'initial',
      },
      fields: [],
    });

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();
    await selectAll();
    await act(async () => {
      screen.getByTestId('next-button').click();
    });

    await waitFor(() => {
      expect(screen.getByText('Найти артефакт')).toBeInTheDocument();
    });

    // Изменить текст single-поля (берём кнопку внутри карточки поля 'goal').
    const fieldCard = screen.getByTestId('field-card-goal');
    const editButton = fieldCard.querySelector(
      'button',
    ) as HTMLButtonElement;
    await act(async () => {
      editButton.click();
    });
    const ta = screen.getByTestId('field-edit-textarea-goal') as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(ta, { target: { value: 'Найти книгу' } });
    });
    await act(async () => {
      screen.getByTestId('field-save-goal').click();
    });

    await waitFor(() => {
      expect(screen.getByText('Найти книгу')).toBeInTheDocument();
    });
  });

  it('отображает suggested_fields из proposal и принимает/отклоняет их', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);
    vi.mocked(api.previewInitialState).mockResolvedValue(makeProposalRead());
    vi.mocked(api.applyInitialState).mockResolvedValue({
      summary: {
        id: 'v1',
        campaign_id: 'camp-1',
        state_version: 1,
        config_version: 1,
        source_kind: 'initial',
      },
      fields: [],
    });

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();
    await selectAll();
    await act(async () => {
      screen.getByTestId('next-button').click();
    });

    await waitFor(() => {
      expect(screen.getByText('Предложенные новые поля (1/1)')).toBeInTheDocument();
    });
    expect(screen.getByText('Найти меч')).toBeInTheDocument();

    // Снимаем галочку "принять" — должно стать (0/1).
    const accept = screen.getByTestId('suggested-accept-0') as HTMLInputElement;
    await act(async () => {
      accept.click();
    });

    await waitFor(() => {
      expect(screen.getByText('Предложенные новые поля (0/1)')).toBeInTheDocument();
    });

    // apply — accepted keys пустой, rejected содержит 'new_goal'.
    await act(async () => {
      screen.getByTestId('apply-button').click();
    });

    await waitFor(() => {
      expect(api.applyInitialState).toHaveBeenCalledWith(
        'camp-1',
        'prop-1',
        1,
        expect.anything(),
        [],
        ['new_goal'],
      );
    });
  });

  it('показывает вопросы и предупреждения из proposal', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);
    vi.mocked(api.previewInitialState).mockResolvedValue(makeProposalRead());

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();
    await selectAll();
    await act(async () => {
      screen.getByTestId('next-button').click();
    });

    await waitFor(() => {
      expect(screen.getByText('Вопросы от модели')).toBeInTheDocument();
    });
    expect(screen.getByText('Какой у вас стиль повествования?')).toBeInTheDocument();
    expect(screen.getByText('Предупреждения (1)')).toBeInTheDocument();
    expect(screen.getByText('document_too_large_for_initial:doc-3')).toBeInTheDocument();
  });

  it('восстанавливает proposal из Redis при повторном открытии', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);
    vi.mocked(api.getInitialStateProposal).mockResolvedValue(
      makeProposalRead() as InitialProposalRead,
    );

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();

    await waitFor(() => {
      // После восстановления попадаем на review сразу.
      expect(screen.getByText('Предложенные новые поля (1/1)')).toBeInTheDocument();
    });
    expect(api.previewInitialState).not.toHaveBeenCalled();
  });

  it('передаёт domainId в api.getSettingsDocuments (регресс)', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([TAG_GLOBAL]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();

    await waitFor(() => {
      expect(api.getSettingsDocuments).toHaveBeenCalledWith({
        domainId: 'dom-1',
        tagIds: ['tag-own', 'tag-global'],
        status: 'indexed',
      });
    });

    await waitFor(() => {
      expect(screen.getByText('lore.md')).toBeInTheDocument();
    });
    expect(screen.getByText('npcs.md')).toBeInTheDocument();
  });

  it('догружает кампанию для получения domainId, если пропс не передан', async () => {
    vi.mocked(api.getCampaign).mockResolvedValue({
      id: 'camp-1',
      name: 'Camp',
      domain_id: 'dom-2',
    } as never);
    vi.mocked(api.getCampaignTags).mockResolvedValue([TAG_OWN]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);
    vi.mocked(api.getSettingsDocuments).mockResolvedValue(DOCS);

    renderWithQuery(<InitialStateButton campaignId="camp-1" />);
    await openWizard();

    await waitFor(() => {
      expect(api.getSettingsDocuments).toHaveBeenCalledWith({
        domainId: 'dom-2',
        tagIds: ['tag-own'],
        status: 'indexed',
      });
    });
  });

  it('показывает баннер "Initial State недоступен", если у кампании нет тегов', async () => {
    vi.mocked(api.getCampaignTags).mockResolvedValue([]);
    vi.mocked(api.getCampaignGlobalTags).mockResolvedValue([]);

    renderWithQuery(<InitialStateButton campaignId="camp-1" domainId="dom-1" />);
    await openWizard();

    await waitFor(() => {
      expect(screen.getByText('Initial State недоступен')).toBeInTheDocument();
    });
    expect(api.getSettingsDocuments).not.toHaveBeenCalled();
  });
});
