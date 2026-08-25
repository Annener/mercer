import { useEffect, useState, useCallback } from 'react';

export type ToastVariant = 'default' | 'success' | 'danger' | 'warning' | 'info';

export interface ToastItem {
  id: string;
  variant: ToastVariant;
  message: string;
  duration?: number;
}

const listeners: Array<(toast: ToastItem) => void> = [];
let idCounter = 0;

export function showToast(
  variant: ToastVariant,
  message: string,
  duration: number = 4000,
): void {
  const id = `t${++idCounter}`;
  listeners.forEach((cb) => cb({ id, variant, message, duration }));
}

export function useToasts(): {
  toasts: ToastItem[];
  dismiss: (id: string) => void;
} {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    const handler = (toast: ToastItem) => {
      setToasts((prev) => [...prev, toast]);
      const ms = toast.duration ?? 4000;
      window.setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== toast.id));
      }, ms);
    };
    listeners.push(handler);
    return () => {
      const idx = listeners.indexOf(handler);
      if (idx >= 0) listeners.splice(idx, 1);
    };
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, dismiss };
}
