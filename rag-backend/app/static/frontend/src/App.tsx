import { useSettingsStore } from '@/stores';
import { ChatPage } from '@/components/chat/ChatPage';
import { SettingsPage } from '@/components/settings/SettingsPage';

export function App() {
  const page = useSettingsStore((s) => s.page);

  if (page === 'settings') {
    return <SettingsPage />;
  }
  return <ChatPage />;
}