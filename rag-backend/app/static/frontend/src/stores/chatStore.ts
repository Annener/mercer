/**
 * Chat store — текущий чат, лента сообщений, состояние стриминга.
 * Заменяет window.currentChatId / window.currentChat / ChatManager.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { api } from '@/api/client';
import type { Chat, ChatMessage, UUID } from '@/api/types';

interface ChatState {
  currentChatId: UUID | null;
  currentChat: Chat | null;
  messages: ChatMessage[];
  loadingChat: boolean;
  isStreaming: boolean;
  streamingContent: string;
  error: string | null;

  loadChat: (chatId: UUID) => Promise<void>;
  appendMessage: (message: ChatMessage) => void;
  setStreamingContent: (content: string) => void;
  setStreaming: (streaming: boolean) => void;
  reset: () => void;
}

export const useChatStore = create<ChatState>()(
  devtools(
    (set) => ({
      currentChatId: null,
      currentChat: null,
      messages: [],
      loadingChat: false,
      isStreaming: false,
      streamingContent: '',
      error: null,

      loadChat: async (chatId) => {
        set({ loadingChat: true, error: null });
        try {
          const data = await api.getChat(chatId);
          set({
            currentChatId: chatId,
            currentChat: data.chat,
            messages: data.messages,
            loadingChat: false,
          });
        } catch (err) {
          set({
            error: err instanceof Error ? err.message : 'Failed to load chat',
            loadingChat: false,
          });
        }
      },

      appendMessage: (message) =>
        set((state) => ({ messages: [...state.messages, message] })),

      setStreamingContent: (content) => set({ streamingContent: content }),

      setStreaming: (streaming) => set({ isStreaming: streaming }),

      reset: () =>
        set({
          currentChatId: null,
          currentChat: null,
          messages: [],
          isStreaming: false,
          streamingContent: '',
        }),
    }),
    { name: 'ChatStore' },
  ),
);