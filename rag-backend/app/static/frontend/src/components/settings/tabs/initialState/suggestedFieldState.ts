import type {
  InitialProposal,
  InitialFieldStatus,
  StateFieldMode,
} from '@/api/types';

export type SuggestedFieldUiState = {
  key: string;
  originalKey: string;
  label: string;
  description: string;
  mode: StateFieldMode;
  initial_status: InitialFieldStatus;
  clarification_question: string | null;
  single_value: { text: string; source_refs: string[] } | null;
  list_value: { items: Array<{ text: string; source_refs: string[] }> } | null;
  accepted: boolean;
};

export function buildSuggestedFromProposal(
  proposal: InitialProposal,
): SuggestedFieldUiState[] {
  return proposal.suggested_fields.map((sf) => ({
    key: sf.key,
    originalKey: sf.key,
    label: sf.label || sf.key,
    description: sf.description || '',
    mode: sf.mode,
    initial_status: sf.initial_status,
    clarification_question: sf.clarification_question ?? null,
    single_value: sf.single_value
      ? {
          text: sf.single_value.text || '',
          source_refs: [...(sf.single_value.source_refs ?? [])],
        }
      : null,
    list_value: sf.list_value
      ? {
          items: (sf.list_value.items ?? []).map((it) => ({
            text: it.text || '',
            source_refs: [...(it.source_refs ?? [])],
          })),
        }
      : null,
    accepted: true,
  }));
}
