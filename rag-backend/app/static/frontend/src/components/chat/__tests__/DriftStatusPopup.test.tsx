import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { DriftStatusPopup } from '../DriftStatusPopup';
import type { DriftStatus } from '@/api/types';

type Listener = (ev: { data: string }) => void;

class FakeEventSource {
  static lastInstance: FakeEventSource | null = null;

  url: string;
  onmessage: Listener | null = null;
  onerror: ((ev: Event) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.lastInstance = this;
  }

  close() {
    this.closed = true;
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

vi.mock('@/api/client', () => ({
  api: {
    getChatEventsStreamUrl: vi.fn((chatId: string) => `/api/chats/${chatId}/events`),
    getDriftStatus: vi.fn().mockResolvedValue({
      chat_id: 'chat-1',
      phase: 'idle',
      started_at: null,
      finished_at: null,
      published_at: new Date().toISOString(),
      message: null,
      drift_hints_count: null,
      draft_ops_count: null,
      draft_summary: null,
      error: null,
    }),
  },
}));

import { api } from '@/api/client';

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.lastInstance = null;
  vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function status(overrides: Partial<DriftStatus> = {}): DriftStatus {
  return {
    chat_id: 'chat-1',
    phase: 'detecting',
    started_at: null,
    finished_at: null,
    published_at: new Date().toISOString(),
    message: 'Анализирую…',
    drift_hints_count: null,
    draft_ops_count: null,
    draft_summary: null,
    error: null,
    ...overrides,
  };
}

function renderPopup() {
  return render(<DriftStatusPopup chatId="chat-1" />);
}

function emitLatest(data: unknown) {
  const es = FakeEventSource.lastInstance;
  if (!es) throw new Error('EventSource not initialised');
  es.emit(data);
}

describe('DriftStatusPopup', () => {
  it('делает catch-up: показывает фазу, если SSE/poll вернули не-idle', async () => {
    vi.mocked(api.getDriftStatus).mockResolvedValueOnce(
      status({ phase: 'detecting', message: 'catch-up' }),
    );
    renderPopup();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText('Drift loop: анализ')).toBeTruthy();
    expect(screen.getByText('catch-up')).toBeTruthy();
  });

  it('показывает фазу detecting после SSE-события', async () => {
    renderPopup();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    act(() => {
      emitLatest(status({ phase: 'detecting', message: 'Анализирую сообщения…' }));
    });
    expect(screen.getByText('Drift loop: анализ')).toBeTruthy();
    expect(screen.getByText('Анализирую сообщения…')).toBeTruthy();
  });

  it('раскрывается и показывает кнопку "Открыть" на draft_ready', async () => {
    renderPopup();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    act(() => {
      emitLatest(
        status({
          phase: 'draft_ready',
          drift_hints_count: 3,
          draft_ops_count: 2,
          draft_summary: 'replace: tone',
        }),
      );
    });
    expect(screen.getByText(/Найдено 2 предложений/)).toBeTruthy();
    expect(screen.getByText('Открыть')).toBeTruthy();
  });

  it('прячется через 5 секунд после idle с сообщением', async () => {
    renderPopup();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    act(() => {
      emitLatest(status({ phase: 'idle', message: 'Готово' }));
    });
    expect(screen.queryByRole('status')).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('не скрывается автоматически на error', async () => {
    renderPopup();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    act(() => {
      emitLatest(status({ phase: 'error', error: 'llm offline' }));
    });
    expect(screen.getByText(/Drift loop: ошибка/)).toBeTruthy();
    expect(screen.getByText('llm offline')).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.queryByRole('status')).toBeTruthy();
  });

  it('ручное закрытие работает', async () => {
    renderPopup();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    act(() => {
      emitLatest(status({ phase: 'detecting' }));
    });
    const closeBtn = screen.getByLabelText('Скрыть');
    fireEvent.click(closeBtn);
    expect(screen.queryByRole('status')).toBeNull();
  });
});
