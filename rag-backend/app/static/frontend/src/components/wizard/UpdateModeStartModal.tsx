import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Button, Field, Modal, Textarea } from '@/components/ui';
import { api } from '@/api/client';
import { useChatStore } from '@/stores';
import type { UUID } from '@/api/types';

interface UpdateModeStartModalProps {
  open: boolean;
  onClose: () => void;
  chatId: UUID;
}

export function UpdateModeStartModal({ open, onClose, chatId }: UpdateModeStartModalProps) {
  const [note, setNote] = useState('');
  const reloadChat = useChatStore((s) => s.loadChat);

  const startMutation = useMutation({
    mutationFn: () => api.updateModeStart(chatId, note),
    onSuccess: async () => {
      await reloadChat(chatId);
      onClose();
      setNote('');
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Запустить Update Mode" size="md">
      <div className="space-y-3 p-4">
        <p className="text-sm text-text-muted">
          Опишите, что должно измениться в контексте кампании. LLM проанализирует хранилища,
          предложит файловые правки и изменения state — вы сможете принять или отклонить их
          перед применением.
        </p>
        <Field label="Заметка / описание изменений:">
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Например: «Игроки достигли города Невервинтер, NPC Арак'нор погиб в бою…»"
            rows={4}
            autoFocus
          />
        </Field>
        {startMutation.error && (
          <p className="text-xs text-danger">
            {(startMutation.error as Error).message ?? 'Не удалось запустить Update Mode'}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose} disabled={startMutation.isPending}>
            Отмена
          </Button>
          <Button
            onClick={() => startMutation.mutate()}
            disabled={startMutation.isPending || !note.trim()}
          >
            {startMutation.isPending ? 'Запуск…' : 'Запустить'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
