import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Field, clsx } from '@/components/ui';
import { useChatStore, useDomainStore, useSettingsStore } from '@/stores';
import { api } from '@/api/client';
import { ChatList } from './ChatList';
import { RenameModal } from './ChatList';
import { SearchDbModal } from '@/components/search/SearchDbModal';
import { CampaignContextModal } from '@/components/wizard/CampaignContextModal';
import { DomainSelectorStrip } from './DomainSelectorStrip';
import type { Chat, CampaignId, Campaign } from '@/api/types';

export function Sidebar() {
  const openSettings = useSettingsStore((s) => s.openSettings);

  const domains = useDomainStore((s) => s.domains);
  const campaigns = useDomainStore((s) => s.campaigns);
  const currentDomainId = useDomainStore((s) => s.currentDomainId);
  const currentCampaignId = useDomainStore((s) => s.currentCampaignId);
  const loadingCampaigns = useDomainStore((s) => s.loadingCampaigns);
  const loadingDomains = useDomainStore((s) => s.loadingDomains);
  const setCurrentDomain = useDomainStore((s) => s.setCurrentDomain);
  const setCurrentCampaign = useDomainStore((s) => s.setCurrentCampaign);
  const loadDomains = useDomainStore((s) => s.loadDomains);
  const loadChat = useChatStore((s) => s.loadChat);

  const queryClient = useQueryClient();
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<{ id: string; title: string } | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [contextMenuCampaign, setContextMenuCampaign] = useState<Campaign | null>(null);
  const [contextMenuPos, setContextMenuPos] = useState<{ x: number; y: number } | null>(null);
  const [contextModalCampaignId, setContextModalCampaignId] = useState<CampaignId | null>(null);
  const errorDismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    void loadDomains();
  }, [loadDomains]);

  // Сброс таймера ошибки при unmount
  useEffect(() => {
    return () => {
      if (errorDismissTimerRef.current) {
        clearTimeout(errorDismissTimerRef.current);
      }
    };
  }, []);

  const chatsQuery = useQuery({
    queryKey: ['chats', currentDomainId, currentCampaignId],
    queryFn: async () => {
      // Для "общего режима" (currentCampaignId === null) передаём '' чтобы бэкенд
      // отфильтровал по campaign_id IS NULL через sentinel '__none__'.
      const data = await api.listChats(currentDomainId, currentCampaignId ?? '');
      return data.chats ?? [];
    },
    enabled: !!currentDomainId,
  });

  const createChatMutation = useMutation({
    mutationFn: (campaignId: CampaignId | null) =>
      api.createChat(currentDomainId, campaignId),
    onSuccess: async (chat) => {
      // Сначала переключаемся на новый чат — пользователь сразу видит его.
      await loadChat(chat.chat_id);
      // Затем инвалидируем кэш списка чатов.
      await queryClient.invalidateQueries({
        queryKey: ['chats', currentDomainId, currentCampaignId],
      });
      await queryClient.invalidateQueries({ queryKey: ['chat', chat.chat_id] });
    },
    onError: () => {
      // Сбрасываем ошибку через 5 секунд, чтобы сообщение не висело вечно.
      if (errorDismissTimerRef.current) {
        clearTimeout(errorDismissTimerRef.current);
      }
      errorDismissTimerRef.current = setTimeout(() => {
        createChatMutation.reset();
        errorDismissTimerRef.current = null;
      }, 5_000);
    },
  });

  const visibleDomains = domains.filter(
    (d) => d.domain_id !== 'default' && d.enabled !== false,
  );

  return (
    <aside className="flex w-64 flex-col border-r border-border bg-surface">
      <header className="space-y-2 border-b border-border p-3">
        <h2 className="text-lg font-semibold text-text">MattMercer</h2>
        <div className="flex flex-col gap-1.5">
          <Button variant="ghost" size="sm" onClick={() => openSettings()}>
            ⚙ Настройки платформы
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setSearchOpen(true)}>
            🔍 Поиск по хранилищу
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => createChatMutation.mutate(currentCampaignId)}
            disabled={!currentDomainId || createChatMutation.isPending}
          >
            + Новая беседа
          </Button>
          {createChatMutation.isError && (
            <p className="text-xs text-danger" role="alert">
              {(createChatMutation.error as Error)?.message ?? 'Не удалось создать беседу'}
            </p>
          )}
        </div>

        <Field label="Домен:">
          <DomainSelectorStrip
            domains={visibleDomains}
            currentDomainId={currentDomainId}
            loading={loadingDomains}
            onSelect={(id) => setCurrentDomain(id)}
          />
        </Field>

        {currentDomainId && (
          <Field label="Контекст:">
            {loadingCampaigns ? (
              <div className="flex items-center gap-2 rounded border border-border bg-surface px-2 py-1.5 text-xs text-text-muted">
                <span
                  className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent"
                  aria-hidden="true"
                />
                Загрузка кампаний…
              </div>
            ) : campaigns.length > 0 ? (
              <div
                className="flex flex-wrap gap-1.5"
                role="radiogroup"
                aria-label="Выбор кампании"
              >
                <CampaignChip
                  icon="🌐"
                  label="Общий режим"
                  selected={currentCampaignId === null}
                  onClick={() => setCurrentCampaign(null)}
                />
                {campaigns.map((c) => {
                  const isSelected = currentCampaignId === c.id;
                  return (
                    <CampaignChip
                      key={c.id}
                      icon={isSelected ? '●' : '📁'}
                      label={c.name}
                      selected={isSelected}
                      onClick={() => setCurrentCampaign(c.id)}
                      onContextMenu={(e: MouseEvent) => {
                        e.preventDefault();
                        setContextMenuCampaign(c);
                        setContextMenuPos({ x: e.clientX, y: e.clientY });
                      }}
                    />
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-text-muted">Нет кампаний в этом домене</p>
            )}
          </Field>
        )}
      </header>

      <ChatList
        chats={chatsQuery.data ?? []}
        loading={chatsQuery.isLoading}
        onRename={(chat: Chat) =>
          setRenameTarget({ id: chat.chat_id, title: chat.title })
        }
      />

      <RenameModal
        open={renameOpen}
        target={renameTarget}
        onClose={() => {
          setRenameOpen(false);
          setRenameTarget(null);
        }}
      />

      <SearchDbModal open={searchOpen} onClose={() => setSearchOpen(false)} />

      {contextMenuCampaign && contextMenuPos && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => {
              setContextMenuCampaign(null);
              setContextMenuPos(null);
            }}
          />
          <div
            className="fixed z-50 min-w-[180px] rounded border border-border bg-surface py-1 shadow-lg"
            style={{ top: contextMenuPos.y, left: contextMenuPos.x }}
          >
            <button
              type="button"
              className="w-full px-3 py-1.5 text-left text-sm hover:bg-surface-2"
              onClick={() => {
                const targetId = contextMenuCampaign.id;
                setContextMenuCampaign(null);
                setContextMenuPos(null);
                setContextModalCampaignId(targetId);
              }}
            >
              Посмотреть контекст…
            </button>
          </div>
        </>
      )}

      <CampaignContextModal
        campaignId={contextModalCampaignId}
        onClose={() => setContextModalCampaignId(null)}
      />
    </aside>
  );
}

interface CampaignChipProps {
  icon: string;
  label: string;
  selected: boolean;
  onClick: () => void;
  onContextMenu?: (e: MouseEvent) => void;
}

function CampaignChip({ icon, label, selected, onClick, onContextMenu }: CampaignChipProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      onContextMenu={onContextMenu}
      title={label}
      className={clsx(
        'inline-flex max-w-full items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition',
        selected
          ? 'border-primary bg-primary/10 text-primary'
          : 'border-border bg-surface text-text hover:bg-surface-2',
      )}
    >
      <span aria-hidden="true" className="shrink-0">{icon}</span>
      <span className="truncate">{label}</span>
    </button>
  );
}