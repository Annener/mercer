/**
 * Domain store — текущий домен, кампания, справочники доменов и кампаний.
 * Заменяет window.currentDomainId / window.currentCampaignId.
 *
 * Persist: currentDomain и currentCampaignId сохраняются в localStorage
 * и восстанавливаются при следующем открытии страницы. Если сохранённая
 * кампания больше не существует — молча сбрасывается.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { api } from '@/api/client';
import { safeStorage } from '@/utils/storage';
import type { Domain, Campaign, DomainId, CampaignId } from '@/api/types';

const STORAGE_KEY_DOMAIN = 'currentDomain';
const STORAGE_KEY_CAMPAIGN = 'currentCampaignId';

function readStored<T extends string>(key: string): T | null {
  try {
    const v = safeStorage.getItem(key);
    return (v as T | null) ?? null;
  } catch {
    return null;
  }
}

function persistString(key: string, value: string | null): void {
  try {
    if (value) safeStorage.setItem(key, value);
    else safeStorage.removeItem(key);
  } catch {
    /* localStorage may be unavailable */
  }
}

interface DomainState {
  domains: Domain[];
  campaigns: Campaign[];
  currentDomainId: DomainId | null;
  currentCampaignId: CampaignId | null;
  loadingDomains: boolean;
  loadingCampaigns: boolean;
  applyingDomainChange: boolean;
  error: string | null;

  loadDomains: () => Promise<void>;
  loadCampaigns: (domainId: DomainId | null) => Promise<void>;
  setCurrentDomain: (domainId: DomainId | null) => void;
  setCurrentCampaign: (campaignId: CampaignId | null) => void;
  reset: () => void;
  _applyDomainChange: (domainId: DomainId | null) => Promise<void>;
}

const initialDomainId = readStored<DomainId>(STORAGE_KEY_DOMAIN);
const initialCampaignId = readStored<CampaignId>(STORAGE_KEY_CAMPAIGN);

export const useDomainStore = create<DomainState>()(
  devtools(
    (set, get) => ({
      domains: [],
      campaigns: [],
      currentDomainId: initialDomainId,
      currentCampaignId: initialCampaignId,
      loadingDomains: false,
      loadingCampaigns: false,
      applyingDomainChange: false,
      error: null,

      _applyDomainChange: async (domainId: DomainId | null) => {
        // Guard от двойного вызова в StrictMode / гонок.
        if (get().applyingDomainChange) return;
        set({ applyingDomainChange: true });
        try {
          set({
            currentDomainId: domainId,
            currentCampaignId: null,
            campaigns: [],
          });
          if (domainId) {
            persistString(STORAGE_KEY_DOMAIN, domainId);
            await get().loadCampaigns(domainId);
            // Восстанавливаем сохранённую кампанию, если она валидна для этого домена.
            const storedCampaign = readStored<CampaignId>(STORAGE_KEY_CAMPAIGN);
            if (storedCampaign) {
              const exists = get().campaigns.some((c) => c.id === storedCampaign);
              if (exists) {
                set({ currentCampaignId: storedCampaign });
              } else {
                // Кампания удалена / не относится к этому домену — молча сбрасываем.
                persistString(STORAGE_KEY_CAMPAIGN, null);
              }
            }
          } else {
            persistString(STORAGE_KEY_DOMAIN, null);
          }
        } finally {
          set({ applyingDomainChange: false });
        }
      },

      loadDomains: async () => {
        if (get().loadingDomains || get().applyingDomainChange) return;
        set({ loadingDomains: true, error: null });
        try {
          const data = await api.getDomains();
          const domains = Array.isArray(data) ? data : (data.domains ?? []);
          const current = get().currentDomainId;
          const stillActive = current
            ? domains.some((d) => d.domain_id === current && d.enabled !== false)
            : false;
          const fallback = domains.find((d) => d.enabled !== false);
          const validCurrent = stillActive ? current : (fallback?.domain_id ?? null);
          set({ domains, loadingDomains: false });
          if (validCurrent !== current) {
            await get()._applyDomainChange(validCurrent);
          } else if (validCurrent && get().campaigns.length === 0) {
            // Домен не менялся, но кампании ещё не загружены (первый mount после reload).
            // Загружаем кампании и валидируем сохранённую currentCampaignId.
            await get().loadCampaigns(validCurrent);
            const storedCampaign = readStored<CampaignId>(STORAGE_KEY_CAMPAIGN);
            if (storedCampaign) {
              const exists = get().campaigns.some((c) => c.id === storedCampaign);
              if (exists) {
                set({ currentCampaignId: storedCampaign });
              } else {
                persistString(STORAGE_KEY_CAMPAIGN, null);
                set({ currentCampaignId: null });
              }
            }
          }
        } catch (err) {
          set({
            error: err instanceof Error ? err.message : 'Failed to load domains',
            loadingDomains: false,
          });
        }
      },

      loadCampaigns: async (domainId) => {
        if (!domainId) {
          set({ campaigns: [], loadingCampaigns: false });
          return;
        }
        set({ loadingCampaigns: true });
        try {
          const data = await api.getCampaigns(domainId);
          const campaigns = Array.isArray(data) ? data : (data.campaigns ?? []);
          set({ campaigns, loadingCampaigns: false });
        } catch (err) {
          set({
            error: err instanceof Error ? err.message : 'Failed to load campaigns',
            loadingCampaigns: false,
          });
        }
      },

      setCurrentDomain: (domainId) => {
        void get()._applyDomainChange(domainId);
      },

      setCurrentCampaign: (campaignId) => {
        set({ currentCampaignId: campaignId });
        persistString(STORAGE_KEY_CAMPAIGN, campaignId);
      },

      reset: () =>
        set({
          campaigns: [],
          currentCampaignId: null,
          applyingDomainChange: false,
        }),
    }),
    { name: 'DomainStore' },
  ),
);
