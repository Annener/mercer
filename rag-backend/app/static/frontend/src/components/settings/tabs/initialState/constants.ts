import { HttpError } from '@/api/http';

export const PER_DOC_TOKEN_LIMIT = 32_000;
export const TOTAL_TOKEN_BUDGET = 64_000;

export const ERROR_MESSAGES: Record<string, string> = {
  no_markdown_documents: 'В домене нет подходящих Markdown-документов.',
  document_not_markdown: 'Некоторые выбранные документы не являются Markdown.',
  document_not_indexed: 'Некоторые документы ещё не проиндексированы.',
  generation_provider_unavailable: 'Генеративная модель недоступна.',
  invalid_generation_output:
    'Модель вернула некорректный ответ. Попробуйте ещё раз.',
  proposal_not_found: 'Предложение не найдено или уже удалено.',
  proposal_expired:
    'Предложение истекло (TTL 3 часа). Сформируйте заново.',
  initial_already_applied: 'Initial State уже применён ранее.',
  config_version_conflict:
    'Конфигурация полей изменилась. Обновите список полей и повторите.',
  source_snapshot_stale:
    'Некоторые источники изменились между preview и apply.',
  campaign_not_found: 'Кампания не найдена.',
  no_campaign_tags:
    'У кампании нет тегов. Добавьте собственные или подключите глобальные, иначе Initial State невозможно сформировать.',
  no_fields_configured_no_propose:
    'У кампании нет ни одного поля. Откройте Wizard ещё раз или используйте режим «Сформировать контекст с помощью ИИ», который сам предложит поля.',
  suggested_field_key_conflict:
    'Конфликт ключа поля: одно из предложенных ИИ полей уже существует в кампании.',
  suggested_field_creation_failed: 'Не удалось создать предложенное ИИ поле.',
};

export interface WizardError {
  code: string | null;
  text: string;
}

export function formatWizardError(err: unknown): WizardError {
  if (err instanceof HttpError) {
    for (const [code, text] of Object.entries(ERROR_MESSAGES)) {
      if (err.isCode(code)) return { code, text };
    }
    if (typeof err.detail === 'string') {
      return { code: null, text: err.detail };
    }
    if (err.detail && typeof err.detail === 'object' && 'code' in err.detail) {
      const code = (err.detail as { code?: unknown }).code;
      const text = (err.detail as { detail?: unknown }).detail;
      return {
        code: typeof code === 'string' ? code : null,
        text: typeof text === 'string' ? text : err.message,
      };
    }
    return { code: null, text: err.message || 'Неизвестная ошибка' };
  }
  if (err instanceof Error) return { code: null, text: err.message };
  return { code: null, text: 'Неизвестная ошибка' };
}

export function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString('ru-RU');
}

export function pluralRu(n: number, forms: [string, string, string]): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1];
  return forms[2];
}
