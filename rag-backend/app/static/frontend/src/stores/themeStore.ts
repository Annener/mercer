/**
 * Theme store — управление light/dark темой через data-theme на <html>.
 * Сохраняется в localStorage.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import type { Theme } from '@/types/common';

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const STORAGE_KEY = 'mercer.theme';

function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'dark' || stored === 'light') return stored;
  } catch {
    /* localStorage may be unavailable */
  }
  return 'light';
}

function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.theme = theme;
}

const initialTheme: Theme = readStoredTheme();
applyTheme(initialTheme);

export const useThemeStore = create<ThemeState>()(
  devtools(
    (set, get) => ({
      theme: initialTheme,
      setTheme: (theme) => {
        applyTheme(theme);
        try {
          localStorage.setItem(STORAGE_KEY, theme);
        } catch {
          /* ignore */
        }
        set({ theme });
      },
      toggleTheme: () => {
        const next: Theme = get().theme === 'light' ? 'dark' : 'light';
        get().setTheme(next);
      },
    }),
    { name: 'ThemeStore' },
  ),
);