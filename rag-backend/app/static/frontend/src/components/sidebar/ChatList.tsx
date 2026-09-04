import { useMutation, useQueryClient } from '@tanstack/react-query';
import { EmptyState } from '@/components/ui';
import { useChatStore, useDomainStore } from '@/stores';
import { api } from '@/api/client';
import { useState } from 'react';
import { Modal, Field, Input, Button } from '@/components/ui';
import type { Chat } from '@/api/types';

interface ChatListProps {
  chats: Chat[];
  loading: boolean;
  onRename: (chat: Chat) => void;
  onViewContext: (chat: Chat) => void;
}

export function ChatList({ chats, loading, onRename, onViewContext }: ChatListProps) {
  const currentChatId = useChatStore((s) => s.currentChatId);
  const loadChat = useChatStore((s) => s.loadChat);
  const currentDomainId = useDomainStore((s) => s.currentDomainId);
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: (chatId: string) => api.deleteChat(chatId),
    onSuccess: (_data, chatId) => {
      void queryClient.invalidateQueries({ queryKey: ['chats', currentDomainId] });
      if (currentChatId === chatId) {
        useChatStore.getState().reset();
      }
    },
  });

  const [openMenu, setOpenMenu] = useState<string | null>(null);

  if (loading) {
    return <div className="p-3 text-xs text-text-muted">Загрузка…</div>;
  }

  if (chats.length === 0) {
    return (
      <div className="p-3">
        <EmptyState
          title="Нет бесед"
          description="Создайте первую беседу для этого домена"
        />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto" onClick={() => setOpenMenu(null)}>
      {chats.map((chat) => {
        const isActive = currentChatId === chat.chat_id;
        return (
          <div
            key={chat.chat_id}
            data-testid={`chat-item-${chat.chat_id}`}
            aria-current={isActive ? 'page' : undefined}
            className={`group flex cursor-pointer items-center justify-between border-b border-l-2 border-border px-3 py-2 text-sm transition hover:bg-surface-2 ${
              isActive
                ? 'border-l-primary bg-primary/10 font-medium text-text'
                : 'border-l-transparent text-text-muted hover:text-text'
            }`}
            onClick={() => {
              setOpenMenu(null);
              void loadChat(chat.chat_id);
              if (chat.campaign_id) {
                useDomainStore.getState().setCurrentCampaign(chat.campaign_id);
              }
            }}
          >
          <span className="flex-1 truncate">{chat.title}</span>
          <button
            type="button"
            className="hidden px-2 text-text-muted hover:text-text group-hover:block"
            onClick={(e) => {
              e.stopPropagation();
              setOpenMenu(openMenu === chat.chat_id ? null : chat.chat_id);
            }}
          >
            ⋮
          </button>
          {openMenu === chat.chat_id && (
            <div
              className="absolute z-10 mt-8 flex flex-col rounded border border-border bg-surface shadow-md"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                className="px-3 py-1.5 text-left text-sm hover:bg-surface-2"
                onClick={() => {
                  setOpenMenu(null);
                  onRename(chat);
                }}
              >
                Переименовать
              </button>
              {chat.campaign_id && (
                <button
                  type="button"
                  className="px-3 py-1.5 text-left text-sm hover:bg-surface-2"
                  onClick={() => {
                    setOpenMenu(null);
                    onViewContext(chat);
                  }}
                >
                  Контекст
                </button>
              )}
              <button
                type="button"
                className="px-3 py-1.5 text-left text-sm text-danger hover:bg-surface-2"
                onClick={() => {
                  if (!confirm('Удалить беседу?')) return;
                  deleteMutation.mutate(chat.chat_id);
                }}
              >
                Удалить
              </button>
            </div>
          )}
          </div>
        );
      })}
    </div>
  );
}

interface RenameModalProps {
  open: boolean;
  target: { id: string; title: string } | null;
  onClose: () => void;
}

export function RenameModal({ open, target, onClose }: RenameModalProps) {
  const [title, setTitle] = useState('');
  const queryClient = useQueryClient();

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api.renameChat(id, title),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['chats'] });
      onClose();
    },
  });

  // Sync local state when modal opens
  if (target && title === '' && open) {
    setTitle(target.title);
  }

  return (
    <Modal open={open} onClose={onClose} title="Переименовать беседу" size="sm">
      <div className="p-4">
        <Field label="Название:">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />
        </Field>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button
            onClick={() => target && renameMutation.mutate({ id: target.id, title })}
            disabled={!title.trim() || renameMutation.isPending}
          >
            Сохранить
          </Button>
        </div>
      </div>
    </Modal>
  );
}