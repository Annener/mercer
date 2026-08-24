import { useState } from 'react';
import { Button, Card } from '@/components/ui';
import { useSettingsStore } from '@/stores';
import { api } from '@/api/client';
import type { CampaignId } from '@/api/types';

export function UpdateModeButton({ campaignId }: { campaignId: CampaignId }) {
  const [opening, setOpening] = useState(false);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const openSettings = useSettingsStore((s) => s.openSettings);

  const start = async () => {
    setError(null);
    setOpening(true);
    try {
      // Update Mode требует активного чата. Переключаемся на страницу чата
      // и передаём данные кампании через store. Это упрощение: реальный
      // сценарий требует существующего чата для кампании.
      const newChat = await api.createChat(null, campaignId);
      await api.updateModeStart(newChat.chat_id, note);
      openSettings('campaigns');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setOpening(false);
    }
  };

  return (
    <Card>
      <h4 className="mb-2 text-sm font-semibold">Campaign Update Mode</h4>
      <p className="mb-2 text-xs text-text-muted">
        Управляемое обновление markdown-контекста кампании: LLM предлагает правки,
        пользователь их ревьюит, indexer применяет с git-фиксацией и reindex.
      </p>
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Опишите изменения…"
        rows={2}
        className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm"
      />
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      <div className="mt-2 flex justify-end">
        <Button size="sm" onClick={start} disabled={opening || !note.trim()}>
          {opening ? 'Запуск…' : 'Запустить Update Mode'}
        </Button>
      </div>
    </Card>
  );
}