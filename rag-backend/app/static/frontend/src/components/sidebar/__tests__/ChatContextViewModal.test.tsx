import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ChatContextViewModal } from '../ChatContextViewModal';

vi.mock('@/api/client', () => ({
  api: {
    getChat: vi.fn(),
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
import type { ChatDetail } from '@/api/types';

function renderWithQueryClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

const BASE_CHAT: ChatDetail = {
  chat: {
    chat_id: '00000000-0000-0000-0000-000000000001',
    title: 'Тестовый чат',
    domain_id: 'dnd',
    campaign_id: 'camp-1',
  },
  messages: [],
};

describe('ChatContextViewModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('не рендерит модал когда chatId=null', () => {
    vi.mocked(api.getChat).mockResolvedValue(BASE_CHAT);
    renderWithQueryClient(
      <ChatContextViewModal chatId={null} onClose={vi.fn()} />,
    );
    expect(screen.queryByText(/Контекст чата/i)).not.toBeInTheDocument();
  });

  it('показывает спиннер пока данные грузятся', () => {
    let resolveGet: ((value: ChatDetail) => void) | undefined;
    vi.mocked(api.getChat).mockImplementation(
      () =>
        new Promise<ChatDetail>((resolve) => {
          resolveGet = resolve;
        }),
    );

    renderWithQueryClient(
      <ChatContextViewModal
        chatId="00000000-0000-0000-0000-000000000001"
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/Загрузка контекста/i)).toBeInTheDocument();
    resolveGet!(BASE_CHAT);
  });

  it('показывает scene_state.explicit когда есть данные', async () => {
    vi.mocked(api.getChat).mockResolvedValue({
      ...BASE_CHAT,
      chat: {
        ...BASE_CHAT.chat,
        metadata: {
          scene_state: {
            explicit: {
              location: 'Таверна «Красный дракон»',
              npc_count: 2,
            },
          },
        },
      },
    });

    renderWithQueryClient(
      <ChatContextViewModal
        chatId="00000000-0000-0000-0000-000000000001"
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText('Таверна «Красный дракон»')).toBeInTheDocument();
    });
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('показывает заглушку для explicit если scene_state пуст', async () => {
    vi.mocked(api.getChat).mockResolvedValue({
      ...BASE_CHAT,
      chat: { ...BASE_CHAT.chat, metadata: { scene_state: {} } },
    });

    renderWithQueryClient(
      <ChatContextViewModal
        chatId="00000000-0000-0000-0000-000000000001"
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Модель ещё не записывала активную сцену/i),
      ).toBeInTheDocument();
    });
  });

  it('рендерит drift hints с confidence-бейджем и фактами', async () => {
    vi.mocked(api.getChat).mockResolvedValue({
      ...BASE_CHAT,
      chat: {
        ...BASE_CHAT.chat,
        metadata: {
          scene_state: {
            drift: {
              _ts: '2026-01-01T12:00:00Z',
              _chat_id: 'chat-1',
              _hints: [
                {
                  fact: 'Игрок переехал в соседний город',
                  adds_field: 'current_location',
                  confidence: 0.85,
                },
                {
                  fact: 'NPC Бранн ранен',
                  contradicts_field: 'npcs.Бранн.состояние',
                  confidence: 0.6,
                },
              ],
            },
          },
        },
      },
    });

    renderWithQueryClient(
      <ChatContextViewModal
        chatId="00000000-0000-0000-0000-000000000001"
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText('Игрок переехал в соседний город')).toBeInTheDocument();
    });
    expect(screen.getByText('NPC Бранн ранен')).toBeInTheDocument();
    expect(screen.getByText('conf=0.85')).toBeInTheDocument();
    expect(screen.getByText('conf=0.60')).toBeInTheDocument();
    expect(screen.getByText('новое поле:')).toBeInTheDocument();
    expect(screen.getByText('противоречит полю:')).toBeInTheDocument();
  });

  it('показывает заглушку для drift hints если их нет', async () => {
    vi.mocked(api.getChat).mockResolvedValue(BASE_CHAT);

    renderWithQueryClient(
      <ChatContextViewModal
        chatId="00000000-0000-0000-0000-000000000001"
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Drift-детектор ещё не нашёл расхождений/i),
      ).toBeInTheDocument();
    });
  });

  it('заголовок содержит title чата', async () => {
    vi.mocked(api.getChat).mockResolvedValue(BASE_CHAT);

    renderWithQueryClient(
      <ChatContextViewModal
        chatId="00000000-0000-0000-0000-000000000001"
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/Контекст чата: Тестовый чат/)).toBeInTheDocument();
    });
  });

  it('закрывается по клику на кнопку ×', async () => {
    vi.mocked(api.getChat).mockResolvedValue(BASE_CHAT);
    const onClose = vi.fn();

    renderWithQueryClient(
      <ChatContextViewModal
        chatId="00000000-0000-0000-0000-000000000001"
        onClose={onClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/Контекст чата: Тестовый чат/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('показывает ошибку и кнопку повтора при сбое загрузки', async () => {
    vi.mocked(api.getChat).mockRejectedValue(new Error('boom'));

    renderWithQueryClient(
      <ChatContextViewModal
        chatId="00000000-0000-0000-0000-000000000001"
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/Не удалось загрузить контекст чата/i)).toBeInTheDocument();
    });
    expect(screen.getByText('Повторить')).toBeInTheDocument();
  });
});
