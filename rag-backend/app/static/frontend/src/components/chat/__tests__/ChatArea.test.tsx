import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ChatArea } from '../ChatArea';
import type { Source } from '@/api/types';

type SSEEvent = Record<string, unknown>;

function makeReadableStream(events: SSEEvent[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const chunks = events.map((e) => encoder.encode(`data: ${JSON.stringify(e)}\n\n`));
  chunks.push(encoder.encode('data: [DONE]\n\n'));
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(c);
      controller.close();
    },
  });
}

type ChatStoreState = {
  currentChatId: string | null;
  currentChat: {
    chat_id: string;
    title: string;
    domain_id: string;
    campaign_id: string | null;
  } | null;
  messages: Array<{
    role: 'user' | 'assistant' | 'system';
    content: string;
    sources?: Source[];
  }>;
  isStreaming: boolean;
  showUpdateModePanel: boolean;
  appendMessage: ReturnType<typeof vi.fn>;
  setStreaming: ReturnType<typeof vi.fn>;
  setStreamingContent: ReturnType<typeof vi.fn>;
  setShowUpdateModePanel: ReturnType<typeof vi.fn>;
};

const chatStoreState: ChatStoreState = {
  currentChatId: 'chat-1',
  currentChat: {
    chat_id: 'chat-1',
    title: 'Test chat',
    domain_id: 'dnd',
    campaign_id: null,
  },
  messages: [],
  isStreaming: false,
  showUpdateModePanel: false,
  appendMessage: vi.fn(),
  setStreaming: vi.fn(),
  setStreamingContent: vi.fn(),
  setShowUpdateModePanel: vi.fn(),
};

const domainStoreState = { currentDomainId: 'dnd' };
const themeStoreState = { theme: 'light' as const, toggleTheme: vi.fn() };

let mockSendMessage: ReturnType<typeof vi.fn>;
let mockPipelineConfirm: ReturnType<typeof vi.fn>;
let mockPipelineResume: ReturnType<typeof vi.fn>;
let mockFullDocConfirm: ReturnType<typeof vi.fn>;
let mockGetContextDraft: ReturnType<typeof vi.fn>;
let mockGetSettingsParams: ReturnType<typeof vi.fn>;

vi.mock('@/stores', () => ({
  useChatStore: (selector: (s: ChatStoreState) => unknown) => selector(chatStoreState),
  useDomainStore: (selector: (s: typeof domainStoreState) => unknown) =>
    selector(domainStoreState),
  useThemeStore: (selector: (s: typeof themeStoreState) => unknown) =>
    selector(themeStoreState),
}));

vi.mock('@/api/client', () => ({
  api: {
    sendMessage: (...args: unknown[]) => mockSendMessage(...args),
    pipelineConfirm: (...args: unknown[]) => mockPipelineConfirm(...args),
    pipelineResume: (...args: unknown[]) => mockPipelineResume(...args),
    fullDocConfirm: (...args: unknown[]) => mockFullDocConfirm(...args),
    getContextDraft: (...args: unknown[]) => mockGetContextDraft(...args),
    getSettingsParams: () => mockGetSettingsParams(),
  },
}));

vi.mock('../ContextDraftCard', async () => {
  const actual = await vi.importActual<typeof import('../ContextDraftCard')>('../ContextDraftCard');
  return {
    ...actual,
    useContextDraftQuery: () => ({ data: undefined, isLoading: false }),
  };
});

vi.mock('@/components/system', () => ({
  ModelHealthIndicator: () => null,
}));

vi.mock('@/components/wizard/UpdateModePanel', () => ({
  UpdateModePanel: () => null,
}));

vi.mock('@/components/chat/cards/FullDocPanel', () => ({
  FullDocPanel: () => null,
}));

vi.mock('@/components/chat/cards/PipelineCards', () => ({
  PipelineConfirmCard: () => null,
  ValidationCard: () => null,
}));

vi.mock('@/components/chat/cards/PipelineExtras', () => ({
  PipelineProgress: () => null,
  PipelineBadge: () => null,
  PipelineStatusLine: () => null,
}));

vi.mock('../DriftStatusPopup', () => ({
  DriftStatusPopup: () => null,
}));

vi.mock('../ChatContextBar', () => ({
  ChatContextBar: () => null,
}));

vi.mock('../Markdown', () => ({
  Markdown: ({ content }: { content: string }) => <div data-testid="md">{content}</div>,
}));

function renderWithQueryClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ChatArea />
    </QueryClientProvider>,
  );
}

const SAMPLES: Source[] = [
  { path: '/vault/dnd/file1.md', page: 1 },
  { path: '/vault/dnd/file2.md', page: null },
];

beforeEach(() => {
  mockSendMessage = vi.fn();
  mockPipelineConfirm = vi.fn();
  mockPipelineResume = vi.fn();
  mockFullDocConfirm = vi.fn();
  mockGetContextDraft = vi.fn().mockResolvedValue({ draft: null });
  mockGetSettingsParams = vi.fn().mockResolvedValue([]);

  chatStoreState.currentChatId = 'chat-1';
  chatStoreState.currentChat = {
    chat_id: 'chat-1',
    title: 'Test chat',
    domain_id: 'dnd',
    campaign_id: null,
  };
  chatStoreState.messages = [];
  chatStoreState.isStreaming = false;
  chatStoreState.showUpdateModePanel = false;
  chatStoreState.appendMessage = vi.fn();
  chatStoreState.setStreaming = vi.fn();
  chatStoreState.setStreamingContent = vi.fn();
  chatStoreState.setShowUpdateModePanel = vi.fn();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('ChatArea — sources и инфо-плашка поиска', () => {
  it('после стрима плашка "Поиск в базе знаний" исчезает и источники попадают в appendMessage', async () => {
    mockSendMessage.mockResolvedValue(
      makeReadableStream([
        { type: 'tool_call', round: 0, tool: 'search_knowledge', queries: ['foo'], reason: 'r' },
        {
          type: 'tool_result',
          round: 0,
          tool: 'search_knowledge',
          hits_count: 2,
          scope: 'domain',
          note: 'n',
          sources: SAMPLES,
        },
        { type: 'token', content: 'Привет' },
        { type: 'token', content: ', мир' },
        {
          type: 'sources',
          sources: [{ path: '/vault/dnd/file3.md', page: 5 }],
        },
      ]),
    );

    renderWithQueryClient();
    const textarea = await screen.findByPlaceholderText('Введите сообщение…');
    fireEvent.change(textarea, { target: { value: 'запрос' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }));

    await waitFor(() => {
      expect(chatStoreState.appendMessage).toHaveBeenCalled();
    });

    const calls = chatStoreState.appendMessage.mock.calls;
    const assistantCall = calls.find(
      (c) => (c[0] as { role?: string })?.role === 'assistant',
    );
    expect(assistantCall).toBeDefined();
    const payload = assistantCall![0] as { role: string; content: string; sources?: Source[] };
    expect(payload.role).toBe('assistant');
    expect(payload.content).toBe('Привет, мир');
    expect(payload.sources).toBeDefined();
    expect(payload.sources!.length).toBe(3);
    const paths = payload.sources!.map((s) => s.path).sort();
    expect(paths).toEqual(
      ['/vault/dnd/file1.md', '/vault/dnd/file2.md', '/vault/dnd/file3.md'].sort(),
    );

    // tool_call inline-элемент НЕ должен оставаться в DOM
    expect(screen.queryByText('Поиск в базе знаний')).toBeNull();
  });

  it('дедуплицирует одинаковые sources из tool_result и финального sources event', async () => {
    mockSendMessage.mockResolvedValue(
      makeReadableStream([
        { type: 'tool_call', round: 0, tool: 'search_knowledge', queries: ['x'] },
        {
          type: 'tool_result',
          round: 0,
          tool: 'search_knowledge',
          hits_count: 1,
          sources: [SAMPLES[0]],
        },
        { type: 'token', content: 'ok' },
        {
          type: 'sources',
          sources: [SAMPLES[0], SAMPLES[1]],
        },
      ]),
    );

    renderWithQueryClient();
    const textarea = await screen.findByPlaceholderText('Введите сообщение…');
    fireEvent.change(textarea, { target: { value: 'q' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }));

    await waitFor(() => {
      expect(chatStoreState.appendMessage).toHaveBeenCalled();
    });

    const assistantCall = chatStoreState.appendMessage.mock.calls.find(
      (c) => (c[0] as { role?: string })?.role === 'assistant',
    )![0] as { sources?: Source[] };
    expect(assistantCall.sources!.length).toBe(2);
    expect(assistantCall.sources!.map((s) => s.path).sort()).toEqual(
      ['/vault/dnd/file1.md', '/vault/dnd/file2.md'].sort(),
    );
  });

  it('если sources нет, поле sources не передаётся в appendMessage', async () => {
    mockSendMessage.mockResolvedValue(
      makeReadableStream([{ type: 'token', content: 'без rag' }]),
    );

    renderWithQueryClient();
    const textarea = await screen.findByPlaceholderText('Введите сообщение…');
    fireEvent.change(textarea, { target: { value: 'q' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }));

    await waitFor(() => {
      expect(chatStoreState.appendMessage).toHaveBeenCalled();
    });

    const assistantCall = chatStoreState.appendMessage.mock.calls.find(
      (c) => (c[0] as { role?: string })?.role === 'assistant',
    )![0] as { role: string; content: string; sources?: Source[] };
    expect(assistantCall.role).toBe('assistant');
    expect(assistantCall.content).toBe('без rag');
    expect(assistantCall.sources).toBeUndefined();
  });
});
