import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { STATUS_DEBOUNCE_MS, useDebouncedStatus } from './useDebouncedStatus';

describe('useDebouncedStatus', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('первый push отображается сразу (displayed=null → нет debounce)', () => {
    const { result } = renderHook(() => useDebouncedStatus(STATUS_DEBOUNCE_MS));
    act(() => {
      result.current.push('Готовлю запрос…');
    });
    expect(result.current.displayed).toBe('Готовлю запрос…');
  });

  it('второй push подряд в течение debounceMs НЕ мерцает — применяется последний по таймеру', () => {
    const { result } = renderHook(() => useDebouncedStatus(STATUS_DEBOUNCE_MS));
    act(() => {
      result.current.push('A');
    });
    expect(result.current.displayed).toBe('A');

    act(() => {
      vi.advanceTimersByTime(50);
    });
    act(() => {
      result.current.push('B');
    });
    // Сразу после push B — displayed ещё 'A' (B в pending).
    expect(result.current.displayed).toBe('A');

    act(() => {
      vi.advanceTimersByTime(STATUS_DEBOUNCE_MS - 50);
    });
    // После истечения окна — только последний (B).
    expect(result.current.displayed).toBe('B');
  });

  it('push после того как предыдущий статус провисел ≥ debounceMs, применяется сразу', () => {
    const { result } = renderHook(() => useDebouncedStatus(STATUS_DEBOUNCE_MS));
    act(() => {
      result.current.push('A');
    });
    // Подождём чуть больше debounce, чтобы displayedAtRef устарел.
    act(() => {
      vi.advanceTimersByTime(STATUS_DEBOUNCE_MS + 10);
    });
    act(() => {
      result.current.push('B');
    });
    expect(result.current.displayed).toBe('B');
  });

  it('clear() сбрасывает и displayed, и pending', () => {
    const { result } = renderHook(() => useDebouncedStatus(STATUS_DEBOUNCE_MS));
    act(() => {
      result.current.push('A');
    });
    // Второй push в течение окна — кладём в pending.
    act(() => {
      vi.advanceTimersByTime(50);
    });
    act(() => {
      result.current.push('B');
    });
    expect(result.current.displayed).toBe('A');

    act(() => {
      result.current.clear();
    });
    expect(result.current.displayed).toBeNull();

    // Таймер должен быть отменён — даже после advanceTimers ничего не появляется.
    act(() => {
      vi.advanceTimersByTime(STATUS_DEBOUNCE_MS);
    });
    expect(result.current.displayed).toBeNull();
  });

  it('clear() идемпотентен, если displayed уже null', () => {
    const { result } = renderHook(() => useDebouncedStatus(STATUS_DEBOUNCE_MS));
    act(() => {
      result.current.clear();
    });
    expect(result.current.displayed).toBeNull();
    act(() => {
      result.current.clear();
    });
    expect(result.current.displayed).toBeNull();
  });

  it('3 быстрых push → пользователь видит только последний после одного таймера', () => {
    const { result } = renderHook(() => useDebouncedStatus(STATUS_DEBOUNCE_MS));
    act(() => {
      result.current.push('first');
    });
    expect(result.current.displayed).toBe('first');

    act(() => {
      vi.advanceTimersByTime(30);
    });
    act(() => {
      result.current.push('second');
    });
    expect(result.current.displayed).toBe('first');

    act(() => {
      vi.advanceTimersByTime(30);
    });
    act(() => {
      result.current.push('third');
    });
    expect(result.current.displayed).toBe('first');

    // Все три укладываются в окно 90мс < 250мс debounce. Должен выстрелить
    // один раз — последний ('third') — когда пройдёт 250мс от первого push.
    act(() => {
      vi.advanceTimersByTime(STATUS_DEBOUNCE_MS - 60);
    });
    expect(result.current.displayed).toBe('third');
  });
});
