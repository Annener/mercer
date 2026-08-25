import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/api/client';
import { HttpError } from '@/api/http';
import type {
  CampaignStateVersion,
  Document,
  InitialProposal,
  InitialProposalRead,
} from '@/api/types';
import {
  type WizardError,
  formatWizardError,
} from './constants';
import {
  buildSuggestedFromProposal,
  type SuggestedFieldUiState,
} from './suggestedFieldState';

export type WizardState =
  | 'idle'
  | 'loading_documents'
  | 'select_documents'
  | 'preview_starting'
  | 'review'
  | 'applying'
  | 'result';

export interface UseInitialStateControllerOptions {
  campaignId: string;
  domainId?: string | null;
  /** Сообщить родителю, что state применён и надо рефрешнуть кампанию. */
  onApplied?: (version: CampaignStateVersion | null) => void;
}

export interface InitialStateController {
  state: WizardState;
  error: WizardError | null;
  setError: (e: WizardError | null) => void;
  documents: Document[];
  documentsLoading: boolean;
  documentsError: string | null;
  tagIds: string[];
  hasNoTags: boolean;
  selectedIds: string[];
  toggleSelect: (id: string) => void;
  proposal: InitialProposalRead | null;
  suggestedFields: SuggestedFieldUiState[];
  patchSuggestedField: (
    index: number,
    patch: Partial<SuggestedFieldUiState>,
  ) => void;
  toggleSuggestedFieldAccept: (index: number) => void;
  appliedVersion: CampaignStateVersion | null;
  loadingPreview: boolean;
  loadingApply: boolean;
  doPreview: () => Promise<void>;
  doApply: () => Promise<void>;
  doBackToSelect: () => void;
}

export function useInitialStateController(
  opts: UseInitialStateControllerOptions,
): InitialStateController {
  const { campaignId, domainId: domainIdProp, onApplied } = opts;

  const [state, setState] = useState<WizardState>('idle');
  const [error, setError] = useState<WizardError | null>(null);

  const [documents, setDocuments] = useState<Document[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [tagIds, setTagIds] = useState<string[]>([]);

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [proposal, setProposal] = useState<InitialProposalRead | null>(null);
  const [suggestedFields, setSuggestedFields] = useState<SuggestedFieldUiState[]>(
    [],
  );
  const [appliedVersion, setAppliedVersion] =
    useState<CampaignStateVersion | null>(null);

  // Раздельные loading-флаги, чтобы UI мог показать спиннер только в нужном
  // месте, не блокируя переключение шагов.
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [loadingApply, setLoadingApply] = useState(false);

  const campaignQuery = useCampaignQuery(campaignId, domainIdProp ?? null);

  // Загрузка документов + попытка восстановить proposal из Redis.
  const load = useCallback(async () => {
    setState('loading_documents');
    setError(null);
    setDocumentsError(null);

    // 1) Теги кампании (свои + глобальные).
    let ownTags: { id: string }[] = [];
    let linkedTags: { id: string }[] = [];
    try {
      [ownTags, linkedTags] = await Promise.all([
        api.getCampaignTags(campaignId).catch(() => []),
        api.getCampaignGlobalTags(campaignId).catch(() => []),
      ]);
    } catch {
      ownTags = [];
      linkedTags = [];
    }
    const mergedTagIds = Array.from(
      new Set([
        ...ownTags.map((t) => String(t.id)),
        ...linkedTags.map((t) => String(t.id)),
      ]),
    );
    setTagIds(mergedTagIds);

    if (mergedTagIds.length === 0) {
      setDocuments([]);
      setState('select_documents');
      return;
    }

    // 2) Резолвим domain_id (из пропса или из кампании).
    const resolvedDomainId =
      domainIdProp ?? campaignQuery.data?.domain_id ?? null;

    // 3) Параллельно: документы + попытка восстановить proposal из Redis.
    setDocumentsLoading(true);
    let fetchedDocs: Document[] = [];
    let existingProposal: InitialProposalRead | null = null;

    try {
      fetchedDocs = await api.getSettingsDocuments({
        domainId: resolvedDomainId,
        tagIds: mergedTagIds,
        status: 'indexed',
      });
    } catch (e) {
      const info = formatWizardError(e);
      // no_campaign_tags обрабатывается отдельно — это не ошибка загрузки
      // документов. Иначе показываем как documentsError.
      if (info.code !== 'no_campaign_tags') {
        setDocumentsError(info.text);
      }
      fetchedDocs = [];
    }
    setDocuments(Array.isArray(fetchedDocs) ? fetchedDocs : []);
    setDocumentsLoading(false);

    try {
      existingProposal = await api.getInitialStateProposal(campaignId);
    } catch {
      existingProposal = null;
    }

    if (existingProposal) {
      setProposal(existingProposal);
      setSuggestedFields(
        buildSuggestedFromProposal(existingProposal.proposal),
      );
      setSelectedIds(
        existingProposal.source_snapshot.map((s) => s.document_id),
      );
      setState('review');
    } else {
      setState('select_documents');
    }
  }, [campaignId, domainIdProp, campaignQuery.data?.domain_id]);

  useEffect(() => {
    if (!campaignId) return;
    if (campaignQuery.isPending) return;
    load().catch((e) => {
      setError(formatWizardError(e));
      setState('select_documents');
    });
    // load завязан на campaignId/domainId/campaignQuery.data.domain_id — но
    // специально не пересчитываем load при каждой смене campaignQuery.data,
    // чтобы не было цикла.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId, domainIdProp, campaignQuery.isPending]);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }, []);

  const patchSuggestedField = useCallback(
    (index: number, patch: Partial<SuggestedFieldUiState>) => {
      setSuggestedFields((prev) =>
        prev.map((sf, i) => (i === index ? { ...sf, ...patch } : sf)),
      );
    },
    [],
  );

  const toggleSuggestedFieldAccept = useCallback((index: number) => {
    setSuggestedFields((prev) =>
      prev.map((sf, i) =>
        i === index ? { ...sf, accepted: !sf.accepted } : sf,
      ),
    );
  }, []);

  const doPreview = useCallback(async () => {
    if (selectedIds.length === 0) return;
    setLoadingPreview(true);
    setError(null);
    setState('preview_starting');
    try {
      const result = await api.previewInitialState(campaignId, selectedIds, {
        propose_fields: true,
      });
      setProposal(result);
      setSuggestedFields(buildSuggestedFromProposal(result.proposal));
      setState('review');
    } catch (e) {
      const info = formatWizardError(e);
      setError(info);
      setState('select_documents');
    } finally {
      setLoadingPreview(false);
    }
  }, [campaignId, selectedIds]);

  const doApply = useCallback(async () => {
    if (!proposal) return;
    setLoadingApply(true);
    setError(null);
    setState('applying');

    // Снимок overrides: existing fields из текущего (отредактированного)
    // suggestedFields списка; suggested-accepted/rejected keys отдельно.
    const proposalOverrides: InitialProposal = {
      fields: proposal.proposal.fields.map((f) => ({
        ...f,
        single_value: f.single_value
          ? { ...f.single_value }
          : null,
        list_value: f.list_value
          ? {
              items: f.list_value.items.map((it) => ({ ...it })),
            }
          : null,
      })),
      suggested_fields: proposal.proposal.suggested_fields,
      questions: [...(proposal.proposal.questions ?? [])],
    };

    const acceptedKeys: string[] = [];
    const rejectedKeys: string[] = [];
    for (const sf of suggestedFields) {
      if (sf.accepted) acceptedKeys.push(sf.key);
      else rejectedKeys.push(sf.key);
    }

    try {
      const version = await api.applyInitialState(
        campaignId,
        proposal.proposal_id,
        proposal.config_version,
        proposalOverrides,
        acceptedKeys,
        rejectedKeys,
      );
      setAppliedVersion(version);
      setState('result');
      if (onApplied) {
        try {
          onApplied(version);
        } catch {
          /* parent handler error — игнорируем, не ломаем UI */
        }
      }
    } catch (e) {
      const info = formatWizardError(e);
      setError(info);
      if (
        info.code === 'initial_already_applied' ||
        info.code === 'source_snapshot_stale' ||
        info.code === 'proposal_expired'
      ) {
        setProposal(null);
        setSuggestedFields([]);
        setState('select_documents');
      } else {
        // suggested_field_* остаются на review — пользователь должен отредактировать.
        setState('review');
      }
    } finally {
      setLoadingApply(false);
    }
  }, [campaignId, proposal, suggestedFields, onApplied]);

  const doBackToSelect = useCallback(() => {
    if (proposal) {
      setSelectedIds(proposal.source_snapshot.map((s) => s.document_id));
    }
    setState('select_documents');
    setError(null);
  }, [proposal]);

  const hasNoTags = tagIds.length === 0;

  return {
    state,
    error,
    setError,
    documents,
    documentsLoading,
    documentsError,
    tagIds,
    hasNoTags,
    selectedIds,
    toggleSelect,
    proposal,
    suggestedFields,
    patchSuggestedField,
    toggleSuggestedFieldAccept,
    appliedVersion,
    loadingPreview,
    loadingApply,
    doPreview,
    doApply,
    doBackToSelect,
  };
}

// Лёгкая обёртка над useQuery (без @tanstack/react-query ради упрощения
// и совместимости с тестами). Прокидывает campaign через api.getCampaign.
function useCampaignQuery(campaignId: string, _preferredDomainId: string | null) {
  const [state, setState] = useState<{
    data: { domain_id?: string } | null;
    isPending: boolean;
  }>({ data: null, isPending: false });
  const lastId = useRef<string | null>(null);

  useEffect(() => {
    if (!campaignId || lastId.current === campaignId) return;
    lastId.current = campaignId;
    if (_preferredDomainId) {
      setState({ data: { domain_id: _preferredDomainId }, isPending: false });
      return;
    }
    setState({ data: null, isPending: true });
    let cancelled = false;
    api
      .getCampaign(campaignId)
      .then((c) => {
        if (cancelled) return;
        setState({ data: { domain_id: c.domain_id }, isPending: false });
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof HttpError && e.status === 404) {
          setState({ data: null, isPending: false });
          return;
        }
        setState({ data: null, isPending: false });
      });
    return () => {
      cancelled = true;
    };
  }, [campaignId, _preferredDomainId]);

  return state;
}
