import { type ReactNode } from 'react';
import { Button } from './Button';
import { Modal } from './Modal';

interface ConfirmModalProps {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'primary';
  onConfirm: () => void;
  onClose: () => void;
  pending?: boolean;
  error?: string | null;
}

export function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = 'Удалить',
  cancelLabel = 'Отмена',
  variant = 'danger',
  onConfirm,
  onClose,
  pending = false,
  error = null,
}: ConfirmModalProps) {
  const handleClose = () => {
    if (pending) return;
    onClose();
  };

  return (
    <Modal open={open} onClose={handleClose} title={title} size="sm">
      <div className="space-y-4 p-4">
        <div className="text-sm text-text">{message}</div>

        {error && (
          <div className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={handleClose} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button
            variant={variant === 'danger' ? 'danger' : 'primary'}
            onClick={onConfirm}
            loading={pending}
            disabled={pending}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  );
}