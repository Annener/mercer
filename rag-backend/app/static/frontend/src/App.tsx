import { useSettingsStore } from '@/stores';
import { ChatPage } from '@/components/chat/ChatPage';
import { SettingsPage } from '@/components/settings/SettingsPage';
import { ToastViewport } from '@/components/ui';

export function App() {
  const page = useSettingsStore((s) => s.page);

  return (
    <>
      <ToastViewport />
      {page === 'settings' ? <SettingsPage /> : <ChatPage />}
    </>
  );
}