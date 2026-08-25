import { useState } from 'react';
import { Button, EmptyState, Modal } from '@/components/ui';
import type { CampaignId, CampaignStateVersion, DomainId } from '@/api/types';
import { WizardStepper, type WizardStep } from './initialState/WizardStepper';
import { WizardErrorBanner } from './initialState/WizardErrorBanner';
import { SelectDocumentsStep } from './initialState/SelectDocumentsStep';
import { ReviewStep } from './initialState/ReviewStep';
import { ResultStep } from './initialState/ResultStep';
import { useInitialStateController } from './initialState/useInitialStateController';
import { ERROR_MESSAGES } from './initialState/constants';

interface InitialStateButtonProps {
  campaignId: CampaignId;
  domainId?: DomainId | null;
  onApplied?: (version: CampaignStateVersion | null) => void;
}

export function InitialStateButton({
  campaignId,
  domainId,
  onApplied,
}: InitialStateButtonProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Сформировать начальный контекст
      </Button>
      {open && (
        <InitialStateWizard
          campaignId={campaignId}
          domainId={domainId ?? undefined}
          onClose={() => setOpen(false)}
          onApplied={onApplied}
        />
      )}
    </>
  );
}

interface InitialStateWizardProps {
  campaignId: CampaignId;
  domainId?: DomainId;
  onClose: () => void;
  onApplied?: (version: CampaignStateVersion | null) => void;
}

function InitialStateWizard({
  campaignId,
  domainId,
  onClose,
  onApplied,
}: InitialStateWizardProps) {
  const ctrl = useInitialStateController({
    campaignId,
    domainId,
    onApplied,
  });

  const step = stateToStep(ctrl.state);

  function handleClose() {
    if (
      (ctrl.state === 'preview_starting' || ctrl.state === 'applying') &&
      !confirm(
        'Прервать формирование Initial State? Прогресс будет потерян.',
      )
    ) {
      return;
    }
    onClose();
  }

  return (
    <Modal open onClose={handleClose} title="Initial State — формирование контекста" size="lg">
      <div className="flex flex-col gap-4">
        <WizardStepper currentStep={step} />

        {ctrl.state === 'loading_documents' ? (
          <LoadingBlock text="Загрузка документов…" />
        ) : ctrl.hasNoTags && ctrl.state === 'select_documents' ? (
          <EmptyState
            title="Initial State недоступен"
            description={ERROR_MESSAGES.no_campaign_tags}
          />
        ) : ctrl.state === 'preview_starting' ? (
          <LoadingBlock text="Генерация Initial State…" />
        ) : ctrl.state === 'applying' ? (
          <LoadingBlock text="Применение Initial State…" />
        ) : ctrl.state === 'select_documents' ? (
          <>
            <WizardErrorBanner
              error={ctrl.error}
              onDismiss={() => ctrl.setError(null)}
            />
            <SelectDocumentsStep
              documents={ctrl.documents}
              documentsLoading={ctrl.documentsLoading}
              documentsError={ctrl.documentsError}
              selectedIds={ctrl.selectedIds}
              onToggle={ctrl.toggleSelect}
              onNext={() => {
                void ctrl.doPreview();
              }}
              loading={ctrl.loadingPreview}
              hintTagCount={ctrl.tagIds.length}
            />
          </>
        ) : ctrl.state === 'review' && ctrl.proposal ? (
          <ReviewStep
            proposal={ctrl.proposal.proposal}
            sourceSnapshot={ctrl.proposal.source_snapshot}
            suggestedFields={ctrl.suggestedFields}
            warnings={ctrl.proposal.warnings}
            onBack={ctrl.doBackToSelect}
            onApply={() => {
              void ctrl.doApply();
            }}
            onSuggestedFieldChange={ctrl.patchSuggestedField}
            onToggleSuggestedFieldAccept={ctrl.toggleSuggestedFieldAccept}
            error={ctrl.error}
            onDismissError={() => ctrl.setError(null)}
            loading={ctrl.loadingApply}
          />
        ) : ctrl.state === 'result' ? (
          <ResultStep version={ctrl.appliedVersion} onClose={onClose} />
        ) : null}
      </div>
    </Modal>
  );
}

function LoadingBlock({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-8 text-sm text-text-muted">
      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-text-muted border-t-transparent" />
      <span>{text}</span>
    </div>
  );
}

function stateToStep(state: ReturnType<typeof useInitialStateController>['state']): WizardStep {
  if (state === 'select_documents' || state === 'loading_documents') return 1;
  if (state === 'review' || state === 'preview_starting' || state === 'applying') return 2;
  if (state === 'result') return 3;
  return 1;
}
