import type { Source } from '@/api/types';

export type AggregatedSource = {
  key: string;
  path: string;
  pages: number[];
};

/**
 * Ключ дедупликации для стрима: (path, page). Симметричен ключу,
 * по которому один и тот же источник не попадёт в `chatStore.messages`
 * дважды во время стрима.
 *
 * `page=null` отделён от page=N, чтобы MD (без page) не схлопывался
 * с PDF (с page).
 */
export function sourceDedupKey(src: Source): string {
  return `${src.path}#${src.page != null ? `p${src.page}` : 'np'}`;
}

/**
 * Группирует источники по `path`, объединяя страницы одного файла.
 *
 * Контракт для UI: один PDF с N страницами → одна строка `[N] file.pdf,
 * стр. p1, p2, …`. MD (page=null) → одна строка `[N] file.md`.
 *
 * Если у одного и того же `path` встречаются записи и с `page`, и без —
 * они попадают в разные бакеты (без-page и с-page), потому что это
 * семантически разные источники (чанк vs целый документ).
 *
 * Сохраняет порядок первого появления; страницы отсортированы по возрастанию.
 */
export function aggregateSources(sources: Source[]): AggregatedSource[] {
  const order: string[] = [];
  const map = new Map<string, AggregatedSource>();
  for (const s of sources) {
    const hasPage = s.page != null;
    const bucketKey = `${s.path}#${hasPage ? 'pages' : 'nopage'}`;
    let bucket = map.get(bucketKey);
    if (!bucket) {
      bucket = { key: bucketKey, path: s.path, pages: [] };
      map.set(bucketKey, bucket);
      order.push(bucketKey);
    }
    if (hasPage && !bucket.pages.includes(s.page as number)) {
      bucket.pages.push(s.page as number);
    }
  }
  for (const b of map.values()) {
    b.pages.sort((a, c) => a - c);
  }
  return order.map((k) => map.get(k)!);
}

/**
 * Извлекает номера цитируемых источников из текста сообщения.
 * Ищет подстроки вида `[1]`, `[2]` и т.д. — ровно те, что вставляет LLM.
 */
export function extractCitedIndices(text: string): Set<number> {
  const cited = new Set<number>();
  const re = /\[(\d+)\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    cited.add(parseInt(m[1]!, 10));
  }
  return cited;
}
