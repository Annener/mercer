import { Sidebar } from '@/components/sidebar/Sidebar';
import { ChatArea } from './ChatArea';

export function ChatPage() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <ChatArea />
    </div>
  );
}