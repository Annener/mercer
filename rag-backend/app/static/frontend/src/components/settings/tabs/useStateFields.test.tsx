import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useStateFields } from './useStateFields';
import { api } from '@/api/client';
import { ToastViewport } from '@/components/ui/Toast';

vi.mock('@/api/client', () => ({
  api: {
    getStateFields: vi.fn(),
    createStateField: vi.fn(),
    updateStateField: vi.fn(),
    deleteStateField: vi.fn(),
    reorderStateFields: vi.fn(),
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

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function renderWithQuery() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderHook(() => useStateFields('camp-1'), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.mocked(api.getStateFields).mockReset();
  vi.mocked(api.createStateField).mockReset();
  vi.mocked(api.updateStateField).mockReset();
  vi.mocked(api.deleteStateField).mockReset();
  vi.mocked(api.reorderStateFields).mockReset();
  vi.mocked(api.getStateFields).mockResolvedValue([]);
  // Глушим console.warn/error — они легитимно пишутся в useStateFields при
  // невалидном UUID, нам не нужно видеть их в выводе тестов.
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('useStateFields — UUID validation (баг #2 регресс)', () => {
  it('deleteStateField НЕ вызывается с невалидным field_id (раньше падал 500)', async () => {
    vi.mocked(api.deleteStateField).mockResolvedValue();

    const { result } = renderWithQuery();
    await act(async () => {
      await result.current.list; // дождаться начальной загрузки
    });

    // Подменяем confirm, чтобы нажатие "remove" прошло без UI-блока.
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    await act(async () => {
      result.current.remove('not-a-uuid');
    });

    expect(api.deleteStateField).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('deleteStateField вызывается с валидным UUID', async () => {
    vi.mocked(api.deleteStateField).mockResolvedValue();
    const validId = '11111111-1111-1111-1111-111111111111';

    const { result } = renderWithQuery();
    await act(async () => {
      await result.current.list;
    });

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    await act(async () => {
      result.current.remove(validId);
    });

    expect(api.deleteStateField).toHaveBeenCalledWith('camp-1', validId);
    confirmSpy.mockRestore();
  });

  it('updateStateField НЕ вызывается с невалидным field_id', async () => {
    vi.mocked(api.updateStateField).mockResolvedValue({} as never);

    const { result } = renderWithQuery();
    await act(async () => {
      await result.current.list;
    });

    await act(async () => {
      result.current.update('not-a-uuid', { enabled: true });
    });

    expect(api.updateStateField).not.toHaveBeenCalled();
  });

  it('toggleEnabled отклоняет невалидный UUID', async () => {
    vi.mocked(api.updateStateField).mockResolvedValue({} as never);

    const { result } = renderWithQuery();
    await act(async () => {
      await result.current.list;
    });

    await act(async () => {
      result.current.toggleEnabled('not-a-uuid', true);
    });

    expect(api.updateStateField).not.toHaveBeenCalled();
  });

  it('регулярка UUID соответствует ожидаемому формату', () => {
    expect(UUID_REGEX.test('11111111-1111-1111-1111-111111111111')).toBe(true);
    expect(UUID_REGEX.test('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')).toBe(true);
    expect(UUID_REGEX.test('not-a-uuid')).toBe(false);
    expect(UUID_REGEX.test('11111111-1111-1111-1111-11111111111')).toBe(false);
    expect(UUID_REGEX.test('')).toBe(false);
  });
});

describe('useStateFields — UI feedback на невалидный field_id (баг #3 регресс)', () => {
  beforeEach(() => {
    vi.mocked(api.getStateFields).mockReset();
    vi.mocked(api.deleteStateField).mockReset();
    vi.mocked(api.updateStateField).mockReset();
    vi.mocked(api.getStateFields).mockResolvedValue([]);
  });

  function renderWithToastViewport() {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    return renderHook(() => useStateFields('camp-1'), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>
          <>
            {children}
            <ToastViewport />
          </>
        </QueryClientProvider>
      ),
    });
  }

  it('remove(undefined) показывает toast и НЕ вызывает API', async () => {
    vi.mocked(api.deleteStateField).mockResolvedValue();
    const { result } = renderWithToastViewport();
    await act(async () => {
      await result.current.list;
    });

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    await act(async () => {
      // @ts-expect-error — тестируем невалидный ввод (undefined)
      result.current.remove(undefined);
    });
    confirmSpy.mockRestore();

    expect(api.deleteStateField).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(
        screen.getByText(/Некорректный ID поля/),
      ).toBeInTheDocument();
    });
  });

  it('remove(пустая строка) показывает toast и НЕ вызывает API', async () => {
    vi.mocked(api.deleteStateField).mockResolvedValue();
    const { result } = renderWithToastViewport();
    await act(async () => {
      await result.current.list;
    });

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    await act(async () => {
      result.current.remove('');
    });
    confirmSpy.mockRestore();

    expect(api.deleteStateField).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(
        screen.getByText(/Некорректный ID поля/),
      ).toBeInTheDocument();
    });
  });

  it('remove с валидным UUID вызывает API (полный happy path)', async () => {
    vi.mocked(api.deleteStateField).mockResolvedValue();
    const validId = '11111111-1111-1111-1111-111111111111';
    const { result } = renderWithToastViewport();
    await act(async () => {
      await result.current.list;
    });

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    await act(async () => {
      result.current.remove(validId);
    });
    // дождаться завершения мутации
    await waitFor(() => {
      expect(api.deleteStateField).toHaveBeenCalledWith('camp-1', validId);
    });
    confirmSpy.mockRestore();
  });
});

describe('StateFieldConfig — клиентский тип ожидает field_id (баг #3 root cause)', () => {
  it('тип StateFieldConfig компилируется с обязательным field_id', () => {
    // Compile-time проверка: если StateFieldConfig не имеет field_id,
    // TypeScript выдаст ошибку при компиляции теста.
    type Field = import('@/api/types').StateFieldConfig;
    const sample: Field = {
      field_id: '11111111-1111-1111-1111-111111111111',
      key: 'k',
      label: 'L',
      mode: 'single',
      enabled: true,
      display_order: 0,
    };
    expect(sample.field_id).toBe('11111111-1111-1111-1111-111111111111');
  });
});
