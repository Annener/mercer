import { useCallback, useRef, useState } from 'react';

/**
 * Минимальный debounce для processing-статусов чата.
 *
 * Поведение:
 *   - `displayed` — строка, которая сейчас показывается (или `null`).
 *   - `push(text)` — обновить displayed, но если предыдущий показан
 *     < `debounceMs` мс назад, отложить последнее значение в pending и
 *     обновить displayed только когда пройдёт остаток окна.
 *   - `clear()` — отменить pending и сбросить displayed в `null`.
 *   - Если за время pending приходит новый `push`, pending перезаписывается
 *     (UI не «дёргается» и видит только последний).
 *
 * API стабильно: `push` и `clear` — это ОДНА и та же функция на всех
 * рендерах (deps `[]`), поэтому колбэки вроде `setProcessingText` в
 * ChatArea не пересоздаются на каждом рендере компонента.
 *
 * Все мутируемые значения (`displayed`, `displayedAt`, `pendingText`,
 * `pendingTimer`) хранятся в одном ref'е — нет stale closures.
 */
export function useDebouncedStatus(debounceMs: number) {
  // `displayed` — единственный state (для ре-рендера компонента).
  // Все остальные поля — в stateRef, чтобы `push`/`clear` могли держать
  // deps=[] (стабильные ссылки) и не зависеть от внешнего `displayed`.
  const [displayed, setDisplayed] = useState<string | null>(null);

  const stateRef = useRef({
    displayed,
    displayedAt: 0,
    pendingText: null as string | null,
    pendingTimer: null as ReturnType<typeof setTimeout> | null,
  });

  const setDisplayedBoth = useCallback((next: string | null) => {
    setDisplayed(next);
    stateRef.current.displayed = next;
    if (next !== null) stateRef.current.displayedAt = Date.now();
    else stateRef.current.displayedAt = 0;
  }, []);

  const push = useCallback(
    (text: string) => {
      const s = stateRef.current;
      const now = Date.now();
      const elapsed = now - s.displayedAt;
      if (s.displayed === null || elapsed >= debounceMs) {
        if (s.pendingTimer !== null) {
          clearTimeout(s.pendingTimer);
          s.pendingTimer = null;
          s.pendingText = null;
        }
        setDisplayedBoth(text);
        return;
      }
      s.pendingText = text;
      if (s.pendingTimer !== null) clearTimeout(s.pendingTimer);
      s.pendingTimer = setTimeout(() => {
        const t = stateRef.current.pendingText;
        stateRef.current.pendingText = null;
        stateRef.current.pendingTimer = null;
        if (t !== null) {
          setDisplayedBoth(t);
        }
      }, debounceMs - elapsed);
    },
    [debounceMs, setDisplayedBoth],
  );

  const clear = useCallback(() => {
    const s = stateRef.current;
    if (s.pendingTimer !== null) {
      clearTimeout(s.pendingTimer);
      s.pendingTimer = null;
    }
    s.pendingText = null;
    if (s.displayed !== null) setDisplayedBoth(null);
  }, [setDisplayedBoth]);

  return { displayed, push, clear };
}

export const STATUS_DEBOUNCE_MS = 250;
