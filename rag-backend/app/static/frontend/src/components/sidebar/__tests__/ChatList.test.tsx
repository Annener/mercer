import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ChatList } from '../ChatList';
import type { Chat } from '@/api/types';

// Моки store — currentChatId управляется через Zustand.
// Используем in-memory state и переопределяем useChatStore / useDomainStore через vi.mock.
const chatStoreState: {
  currentChatId: string | null;
  loadChat: ReturnType<typeof vi.fn>;
  reset: ReturnType<typeof vi.fn>;
} = {
  currentChatId: null,
  loadChat: vi.fn(),
  reset: vi.fn(),
};

const domainStoreState: { currentDomainId: string | null } = {
  currentDomainId: 'dnd',
};

vi.mock('@/stores', () => ({
  useChatStore: (selector: (s: typeof chatStoreState) => unknown) =>
    selector(chatStoreState),
  useDomainStore: (selector: (s: typeof domainStoreState) => unknown) =>
    selector(domainStoreState),
}));

vi.mock('@/api/client', () => ({
  api: {
    deleteChat: vi.fn().mockResolvedValue(undefined),
  },
}));

function renderWithQueryClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

const CHATS: Chat[] = [
  {
    chat_id: 'chat-1',
    title: 'Тест 1',
    domain_id: 'dnd',
    campaign_id: null,
  },
  {
    chat_id: 'chat-2',
    title: 'Тест 2',
    domain_id: 'dnd',
    campaign_id: null,
  },
  {
    chat_id: 'chat-3',
    title: 'Тест 3 (в кампании)',
    domain_id: 'dnd',
    campaign_id: 'camp-1',
  },
];

describe('ChatList — подсветка активного чата', () => {
  beforeEach(() => {
    chatStoreState.currentChatId = null;
    chatStoreState.loadChat = vi.fn();
    chatStoreState.reset = vi.fn();
    domainStoreState.currentDomainId = 'dnd';
  });

  it('при currentChatId=null ни один чат не подсвечен', () => {
    renderWithQueryClient(
      <ChatList chats={CHATS} loading={false} onRename={vi.fn()} onViewContext={vi.fn()} />,
    );

    CHATS.forEach((c) => {
      const item = screen.getByTestId(`chat-item-${c.chat_id}`);
      expect(item).toHaveClass('border-l-transparent');
      expect(item).not.toHaveClass('bg-primary/10');
      expect(item).not.toHaveClass('font-medium');
      expect(item).not.toHaveClass('border-l-primary');
    });
  });

  it('активный чат получает border-l-primary, bg-primary/10, font-medium', () => {
    chatStoreState.currentChatId = 'chat-1';
    renderWithQueryClient(
      <ChatList chats={CHATS} loading={false} onRename={vi.fn()} onViewContext={vi.fn()} />,
    );

    const active = screen.getByTestId('chat-item-chat-1');
    expect(active).toHaveClass('border-l-primary');
    expect(active).toHaveClass('bg-primary/10');
    expect(active).toHaveClass('font-medium');
    expect(active).toHaveClass('text-text');
    expect(active).toHaveAttribute('aria-current', 'page');

    const inactive = screen.getByTestId('chat-item-chat-2');
    expect(inactive).toHaveClass('border-l-transparent');
    expect(inactive).toHaveClass('text-text-muted');
    expect(inactive).not.toHaveClass('bg-primary/10');
    expect(inactive).not.toHaveAttribute('aria-current');
  });

  it('клик по чату вызывает loadChat с правильным id', () => {
    renderWithQueryClient(
      <ChatList chats={CHATS} loading={false} onRename={vi.fn()} onViewContext={vi.fn()} />,
    );

    fireEvent.click(screen.getByText('Тест 2'));
    expect(chatStoreState.loadChat).toHaveBeenCalledWith('chat-2');
  });

  it('рендерит EmptyState при пустом списке', () => {
    renderWithQueryClient(
      <ChatList chats={[]} loading={false} onRename={vi.fn()} onViewContext={vi.fn()} />,
    );
    expect(screen.getByText(/Нет бесед/i)).toBeInTheDocument();
  });

  it('рендерит индикатор загрузки', () => {
    renderWithQueryClient(
      <ChatList chats={[]} loading={true} onRename={vi.fn()} onViewContext={vi.fn()} />,
    );
    expect(screen.getByText(/Загрузка/i)).toBeInTheDocument();
  });
});

describe('ChatList — пункт меню «Контекст»', () => {
  beforeEach(() => {
    chatStoreState.currentChatId = null;
    chatStoreState.loadChat = vi.fn();
    chatStoreState.reset = vi.fn();
    domainStoreState.currentDomainId = 'dnd';
  });

  function openMenuFor(chatId: string) {
    const item = screen.getByTestId(`chat-item-${chatId}`);
    const menuButton = item.querySelector('button') as HTMLButtonElement;
    fireEvent.click(menuButton);
  }

  it('пункт «Контекст» отображается для чата с campaign_id', () => {
    renderWithQueryClient(
      <ChatList chats={CHATS} loading={false} onRename={vi.fn()} onViewContext={vi.fn()} />,
    );

    openMenuFor('chat-3');
    expect(screen.getByText('Контекст')).toBeInTheDocument();
  });

  it('пункт «Контекст» НЕ отображается для чата без campaign_id', () => {
    renderWithQueryClient(
      <ChatList chats={CHATS} loading={false} onRename={vi.fn()} onViewContext={vi.fn()} />,
    );

    openMenuFor('chat-1');
    expect(screen.queryByText('Контекст')).not.toBeInTheDocument();
  });

  it('клик по «Контекст» вызывает onViewContext с правильным chat', () => {
    const onViewContext = vi.fn();
    renderWithQueryClient(
      <ChatList chats={CHATS} loading={false} onRename={vi.fn()} onViewContext={onViewContext} />,
    );

    openMenuFor('chat-3');
    fireEvent.click(screen.getByText('Контекст'));

    expect(onViewContext).toHaveBeenCalledTimes(1);
    expect(onViewContext).toHaveBeenCalledWith(
      expect.objectContaining({ chat_id: 'chat-3', campaign_id: 'camp-1' }),
    );
  });
});
