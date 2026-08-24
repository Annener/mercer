import { useQuery } from '@tanstack/react-query';
import { Modal } from '@/components/ui';
import { Markdown } from '@/components/chat/Markdown';
import { api } from '@/api/client';
import type {
  CampaignId,
  CampaignStateFieldValue,
  CampaignStateListItemRead,
  CampaignStateSingleValueRead,
  CampaignStateVersion,
} from '@/api/types';

interface CampaignContextModalProps {
  campaignId: CampaignId | null;
  onClose: () => void;
}

export function CampaignContextModal({ campaignId, onClose }: CampaignContextModalProps) {
  const open = campaignId !== null;

  const campaignQuery = useQuery({
    queryKey: ['campaign', campaignId],
    queryFn: () => api.getCampaign(campaignId!),
    enabled: !!campaignId,
  });

  const stateQuery = useQuery({
    queryKey: ['campaign-state', campaignId],
    queryFn: () => api.getActiveCampaignState(campaignId!),
    enabled: !!campaignId,
    retry: false,
  });

  const title = campaignQuery.data?.name
    ? `Контекст: ${campaignQuery.data.name}`
    : 'Контекст кампании';

  return (
    <Modal open={open} onClose={onClose} title={title} size="lg">
      <div className="p-4">
        {!campaignId && null}
        {campaignQuery.isLoading && (
          <div className="flex items-center gap-2 text-sm text-text-muted">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            Загрузка кампании…
          </div>
        )}
        {stateQuery.isLoading && !stateQuery.error && (
          <div className="flex items-center gap-2 text-sm text-text-muted">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            Загрузка состояния…
          </div>
        )}
        {stateQuery.error && (
          <div className="space-y-2 text-sm text-danger">
            <p>Не удалось загрузить состояние кампании.</p>
            <button
              type="button"
              onClick={() => {
                void stateQuery.refetch();
              }}
              className="rounded border border-border bg-surface px-2 py-1 text-xs text-text hover:bg-surface-2"
            >
              Повторить
            </button>
          </div>
        )}
        {stateQuery.data !== undefined && !stateQuery.isLoading && (
          <CampaignStateView state={stateQuery.data} />
        )}
      </div>
    </Modal>
  );
}

function CampaignStateView({ state }: { state: CampaignStateVersion | null }) {
  if (!state || !state.fields || state.fields.length === 0) {
    return (
      <div className="rounded border border-dashed border-border bg-surface-2/40 p-4 text-sm text-text-muted">
        Кампания ещё не инициализирована (Initial State не применён).
      </div>
    );
  }

  const summary = state.summary;

  return (
    <div className="space-y-4">
      <div className="text-xs text-text-muted">
        Версия #{summary.state_version} · конфиг v{summary.config_version}
        {summary.created_at && (
          <>
            {' · '}
            обновлено {new Date(summary.created_at).toLocaleString('ru-RU')}
          </>
        )}
        {summary.source_kind && (
          <>
            {' · '}
            источник: <span className="font-mono">{summary.source_kind}</span>
          </>
        )}
      </div>
      <div className="space-y-3">
        {state.fields.map((field) => (
          <StateFieldRow key={field.field_key} field={field} />
        ))}
      </div>
    </div>
  );
}

function StateFieldRow({ field }: { field: CampaignStateFieldValue }) {
  const label = field.field_label ?? field.field_key;

  if (!field.enabled) return null;

  if (field.mode === 'single') {
    const sv = field.single_value ?? null;
    return (
      <SingleFieldCard
        label={label}
        value={sv}
        sourceCount={sv?.source_refs?.length ?? 0}
      />
    );
  }

  if (field.mode === 'list') {
    const items = field.items ?? [];
    return (
      <ListFieldCard
        label={label}
        items={items}
      />
    );
  }

  return null;
}

function SingleFieldCard({
  label,
  value,
  sourceCount,
}: {
  label: string;
  value: CampaignStateSingleValueRead | null;
  sourceCount: number;
}) {
  return (
    <div className="rounded border border-border bg-surface-2/40 p-3">
      <header className="mb-1.5 flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          {label}
        </h4>
        {sourceCount > 0 && (
          <span
            className="rounded bg-info/10 px-1.5 text-[10px] font-medium text-info"
            title="Количество ссылок на источники"
          >
            {sourceCount} ист.
          </span>
        )}
      </header>
      {value ? (
        value.text ? (
          <Markdown content={value.text} />
        ) : (
          <p className="text-sm italic text-text-muted">— пусто —</p>
        )
      ) : (
        <p className="text-sm italic text-text-muted">— значение не задано —</p>
      )}
    </div>
  );
}

function ListFieldCard({
  label,
  items,
}: {
  label: string;
  items: CampaignStateListItemRead[];
}) {
  return (
    <div className="rounded border border-border bg-surface-2/40 p-3">
      <header className="mb-1.5 flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          {label}
        </h4>
        <span className="text-[10px] text-text-muted">
          {items.length} {items.length === 1 ? 'элемент' : 'элементов'}
        </span>
      </header>
      {items.length === 0 ? (
        <p className="text-sm italic text-text-muted">— пусто —</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li
              key={item.item_key}
              className={`flex items-start gap-2 rounded px-2 py-1 text-sm ${
                item.resolved ? 'bg-success/5 line-through text-text-muted' : 'bg-surface'
              }`}
            >
              <span className="mt-0.5 shrink-0 text-text-muted">•</span>
              <span className="flex-1">
                {item.text || <em className="text-text-muted">(пусто)</em>}
              </span>
              {item.resolved && (
                <span
                  className="shrink-0 rounded bg-success/15 px-1.5 text-[10px] font-medium text-success"
                  title="Закрытый / разрешённый пункт"
                >
                  ✓
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
