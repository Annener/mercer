import { type ReactNode } from 'react';
import { Button, DomainRail, Tabs } from '@/components/ui';
import { useSettingsStore, type SettingsTab } from '@/stores';
import { useDomainStore } from '@/stores';
import { DomainsTab } from './tabs/DomainsTab';
import { VaultsTab } from './tabs/VaultsTab';
import { ModelsTab } from './tabs/ModelsTab';
import { ParamsTab } from './tabs/ParamsTab';
import { PipelinesTab } from './tabs/PipelinesTab';
import { CampaignsTab } from './tabs/CampaignsTab';
import { DocumentsTab } from './tabs/DocumentsTab';

const TAB_ITEMS: Array<{ id: SettingsTab; label: string }> = [
  { id: 'domains', label: 'Домены' },
  { id: 'vaults', label: 'Vault' },
  { id: 'models', label: 'Модели' },
  { id: 'params', label: 'Параметры' },
  { id: 'pipelines', label: 'Pipelines' },
  { id: 'campaigns', label: 'Кампании' },
  { id: 'documents', label: 'Документы' },
];

const TABS_WITH_RAIL: ReadonlySet<SettingsTab> = new Set([
  'vaults',
  'pipelines',
  'campaigns',
  'documents',
]);

export function SettingsPage() {
  const activeTab = useSettingsStore((s) => s.activeSettingsTab);
  const setActiveTab = useSettingsStore((s) => s.setActiveTab);
  const openChat = useSettingsStore((s) => s.openChat);

  return (
    <main className="flex h-full flex-col bg-bg">
      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-3">
        <h2 className="text-lg font-semibold">Настройки платформы</h2>
        <Button variant="ghost" onClick={openChat}>
          ← Назад к чату
        </Button>
      </header>

      <div className="px-4 pt-3">
        <Tabs
          items={TAB_ITEMS.map((t) => ({ id: t.id, label: t.label }))}
          value={activeTab}
          onChange={(id) => setActiveTab(id as SettingsTab)}
        />
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <SettingsContent tab={activeTab} />
      </div>
    </main>
  );
}

function SettingsContent({ tab }: { tab: SettingsTab }) {
  const inner = renderTab(tab);
  if (!TABS_WITH_RAIL.has(tab)) return inner;
  return <RailLayout tab={tab}>{inner}</RailLayout>;
}

function renderTab(tab: SettingsTab): ReactNode {
  switch (tab) {
    case 'domains':
      return <DomainsTab />;
    case 'vaults':
      return <VaultsTab />;
    case 'models':
      return <ModelsTab />;
    case 'params':
      return <ParamsTab />;
    case 'pipelines':
      return <PipelinesTab />;
    case 'campaigns':
      return <CampaignsTab />;
    case 'documents':
      return <DocumentsTab />;
    default:
      return null;
  }
}

interface RailLayoutProps {
  tab: SettingsTab;
  children: ReactNode;
}

function RailLayout({ tab, children }: RailLayoutProps) {
  const domains = useDomainStore((s) => s.domains);
  const selectedRailDomainId = useSettingsStore((s) => s.selectedRailDomainId);
  const setSelectedRailDomain = useSettingsStore((s) => s.setSelectedRailDomain);

  return (
    <div className="-mt-[18px] grid grid-cols-1 gap-[18px] md:grid-cols-[180px_1fr] md:gap-0">
      <DomainRail
        domains={domains}
        selectedDomainId={selectedRailDomainId}
        onSelect={setSelectedRailDomain}
        hideAll={tab === 'documents'}
      />
      <div className="min-w-0 md:pl-[18px] md:pt-[18px]">{children}</div>
    </div>
  );
}