import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { DomainId } from '@/api/types';

interface Props {
  domainId: DomainId | null | undefined;
}

const POLL_IDLE_MS = 30_000;
const POLL_ACTIVE_MS = 5_000;

function pluralizeFiles(n: number): string {
  const mod100 = n % 100;
  const mod10 = n % 10;
  if (mod100 >= 11 && mod100 <= 19) return 'файлов';
  if (mod10 === 1) return 'файл';
  if (mod10 >= 2 && mod10 <= 4) return 'файла';
  return 'файлов';
}

export function PendingIndexBanner({ domainId }: Props) {
  const queryClient = useQueryClient();
  const [indexing, setIndexing] = useState(false);

  const pendingQuery = useQuery({
    queryKey: ['domainPending', domainId ?? null],
    queryFn: () => api.getDomainPendingFiles(domainId as DomainId),
    enabled: !!domainId,
    refetchInterval: () => (indexing ? POLL_ACTIVE_MS : POLL_IDLE_MS),
    refetchIntervalInBackground: false,
    staleTime: POLL_IDLE_MS,
  });

  const totalPending = pendingQuery.data?.total_pending ?? 0;

  useEffect(() => {
    if (!indexing) return;
    if (pendingQuery.data && totalPending === 0) {
      setIndexing(false);
    }
  }, [indexing, pendingQuery.data, totalPending]);

  const triggerMutation = useMutation({
    mutationFn: () => {
      if (!domainId) throw new Error('No domain');
      return api.triggerDomainIndex(domainId);
    },
    onMutate: () => {
      setIndexing(true);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['domainPending', domainId ?? null] });
    },
    onError: () => {
      setIndexing(false);
    },
  });

  if (!domainId) return null;
  if (!indexing && totalPending === 0) return null;

  const onTrigger = () => {
    if (triggerMutation.isPending) return;
    triggerMutation.mutate();
  };

  if (indexing) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="inline-flex items-center gap-2 rounded-md border border-sky-300 bg-sky-50 px-2.5 py-1 text-xs text-sky-800"
      >
        <svg
          className="animate-spin text-sky-600"
          width="13"
          height="13"
          viewBox="0 0 14 14"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <circle
            cx="7"
            cy="7"
            r="5.5"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeDasharray="20 14"
          />
        </svg>
        <span>
          {totalPending > 0
            ? `Индексация… (осталось ${totalPending} ${pluralizeFiles(totalPending)})`
            : 'Индексация…'}
        </span>
      </div>
    );
  }

  return (
    <div
      role="status"
      className="inline-flex items-center gap-2 rounded-md border border-emerald-400 bg-emerald-50 px-2.5 py-1 text-xs text-emerald-800"
    >
      <span>{`${totalPending} ${pluralizeFiles(totalPending)} ожидает индексации`}</span>
      <button
        type="button"
        onClick={onTrigger}
        disabled={triggerMutation.isPending}
        className="inline-flex items-center rounded border border-emerald-500 bg-emerald-600 px-2 py-0.5 text-xs font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/40"
        title="Запустить индексацию ожидающих файлов"
      >
        {triggerMutation.isPending ? 'Запускается…' : 'Запустить индексацию'}
      </button>
    </div>
  );
}