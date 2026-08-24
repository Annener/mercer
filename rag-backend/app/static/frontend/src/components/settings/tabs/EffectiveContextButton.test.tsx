import { describe, it, expect, vi } from 'vitest';
import type { ReactNode } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EffectiveContextButton } from './EffectiveContextButton';
import type { EffectiveContextRead } from '@/api/types';

vi.mock('@/api/client', () => ({
  api: {
    getEffectiveContext: vi.fn(),
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

const SAMPLE: EffectiveContextRead = {
  campaign_id: 'camp-1',
  blocks: [
    { name: 'system_prompt', text: 'You are a helpful assistant.', estimated_tokens: 5 },
    { name: 'campaign_state', text: 'Фокус: дизайн', estimated_tokens: 3 },
  ],
  total_tokens: 8,
  budget: 800,
  truncated_fields: [],
  state_version: 1,
};

function renderWithQuery(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('EffectiveContextButton', () => {
  it('рендерит блоки с реальным текстом (регресс: content→text)', async () => {
    vi.mocked(api.getEffectiveContext).mockResolvedValue(SAMPLE);
    renderWithQuery(<EffectiveContextButton campaignId="camp-1" />);

    screen.getByRole('button', { name: /Debug effective context/i }).click();

    await waitFor(() => {
      expect(
        screen.getByText(/You are a helpful assistant/),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(/Фокус: дизайн/)).toBeInTheDocument();
    expect(api.getEffectiveContext).toHaveBeenCalledWith('camp-1');
  });

  it('показывает метрики total_tokens и budget', async () => {
    vi.mocked(api.getEffectiveContext).mockResolvedValue(SAMPLE);
    renderWithQuery(<EffectiveContextButton campaignId="camp-1" />);
    await act(async () => {
      screen.getByRole('button', { name: /Debug effective context/i }).click();
    });

    await waitFor(() => {
      expect(screen.getAllByText(/Всего токенов/).length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText(/бюджет/).length).toBeGreaterThan(0);
  });
});