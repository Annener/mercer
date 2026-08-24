/**
 * Settings store — UI-состояние страницы настроек:
 *   - какая страница сейчас видна (chat vs settings)
 *   - какой таб настроек активен
 *   - выбранный домен в DomainRail (общий для всех табов с rail)
 *
 * Заменяет window.activeSettingsTab и переключение .hidden на index.html.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import type { DomainId } from '@/api/types';

export type SettingsTab =
  | 'domains'
  | 'vaults'
  | 'models'
  | 'params'
  | 'pipelines'
  | 'campaigns'
  | 'documents';

export type Page = 'chat' | 'settings';

interface SettingsState {
  page: Page;
  activeSettingsTab: SettingsTab;
  // null = «Все домены». Не сохраняется в localStorage — обнуляется при перезагрузке.
  selectedRailDomainId: DomainId | null;
  openSettings: (tab?: SettingsTab) => void;
  openChat: () => void;
  setActiveTab: (tab: SettingsTab) => void;
  setSelectedRailDomain: (id: DomainId | null) => void;
}

export const useSettingsStore = create<SettingsState>()(
  devtools(
    (set) => ({
      page: 'chat',
      activeSettingsTab: 'domains',
      selectedRailDomainId: null,

      openSettings: (tab) =>
        set((state) => ({
          page: 'settings',
          activeSettingsTab: tab ?? state.activeSettingsTab,
        })),

      openChat: () => set({ page: 'chat' }),

      setActiveTab: (tab) => set({ activeSettingsTab: tab }),

      setSelectedRailDomain: (id) => set({ selectedRailDomainId: id }),
    }),
    { name: 'SettingsStore' },
  ),
);