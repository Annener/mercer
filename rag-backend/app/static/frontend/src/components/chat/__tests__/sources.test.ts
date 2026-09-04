import { describe, it, expect } from 'vitest';
import { aggregateSources, extractCitedIndices, sourceDedupKey } from '../sources';
import type { Source } from '@/api/types';

describe('sourceDedupKey', () => {
  it('page=null и page=N дают разные ключи для одного path', () => {
    const a: Source = { path: '/vault/file.md', page: null };
    const b: Source = { path: '/vault/file.md', page: 1 };
    expect(sourceDedupKey(a)).not.toBe(sourceDedupKey(b));
  });

  it('разные page дают разные ключи для одного path', () => {
    expect(sourceDedupKey({ path: '/vault/file.pdf', page: 1 }))
      .not.toBe(sourceDedupKey({ path: '/vault/file.pdf', page: 2 }));
  });

  it('одинаковые (path, page) дают одинаковый ключ', () => {
    expect(sourceDedupKey({ path: '/vault/file.md', page: null }))
      .toBe(sourceDedupKey({ path: '/vault/file.md', page: null }));
    expect(sourceDedupKey({ path: '/vault/file.pdf', page: 5 }))
      .toBe(sourceDedupKey({ path: '/vault/file.pdf', page: 5 }));
  });
});

describe('aggregateSources — дедупликация и группировка страниц', () => {
  it('схлопывает одинаковые MD записи', () => {
    const sources: Source[] = [
      { path: '/vault/a.md', page: null },
      { path: '/vault/a.md', page: null },
      { path: '/vault/a.md', page: null },
      { path: '/vault/a.md', page: null },
    ];
    expect(aggregateSources(sources)).toEqual([
      { key: '/vault/a.md#nopage', path: '/vault/a.md', pages: [] },
    ]);
  });

  it('группирует несколько страниц одного PDF в один агрегат', () => {
    const sources: Source[] = [
      { path: '/vault/manual.pdf', page: 12 },
      { path: '/vault/manual.pdf', page: 7 },
      { path: '/vault/manual.pdf', page: 3 },
      { path: '/vault/manual.pdf', page: 7 },
    ];
    expect(aggregateSources(sources)).toEqual([
      { key: '/vault/manual.pdf#pages', path: '/vault/manual.pdf', pages: [3, 7, 12] },
    ]);
  });

  it('разделяет MD (page=null) и PDF (с page) одного path', () => {
    const sources: Source[] = [
      { path: '/vault/file', page: null },
      { path: '/vault/file', page: 1 },
    ];
    const result = aggregateSources(sources);
    expect(result).toHaveLength(2);
    const md = result.find((s) => s.key.endsWith('#nopage'));
    const pdf = result.find((s) => s.key.endsWith('#pages'));
    expect(md?.pages).toEqual([]);
    expect(pdf?.pages).toEqual([1]);
  });

  it('сохраняет порядок первого появления', () => {
    const sources: Source[] = [
      { path: '/vault/b.md', page: null },
      { path: '/vault/a.md', page: null },
      { path: '/vault/c.pdf', page: 5 },
    ];
    expect(aggregateSources(sources).map((s) => s.path)).toEqual([
      '/vault/b.md',
      '/vault/a.md',
      '/vault/c.pdf',
    ]);
  });

  it('PDF с одной страницей — pages из одного элемента', () => {
    expect(aggregateSources([{ path: '/m.pdf', page: 5 }])).toEqual([
      { key: '/m.pdf#pages', path: '/m.pdf', pages: [5] },
    ]);
  });

  it('MD без page — pages пустой массив', () => {
    expect(aggregateSources([{ path: '/x.md', page: null }])).toEqual([
      { key: '/x.md#nopage', path: '/x.md', pages: [] },
    ]);
  });

  it('несколько разных файлов с разными страницами', () => {
    const sources: Source[] = [
      { path: '/m1.pdf', page: 1 },
      { path: '/m2.pdf', page: 5 },
      { path: '/m1.pdf', page: 2 },
      { path: '/x.md', page: null },
      { path: '/m2.pdf', page: 3 },
    ];
    const result = aggregateSources(sources);
    expect(result.map((s) => `${s.path}:[${s.pages.join(',')}]`)).toEqual([
      '/m1.pdf:[1,2]',
      '/m2.pdf:[3,5]',
      '/x.md:[]',
    ]);
  });

  it('пустой вход → пустой выход', () => {
    expect(aggregateSources([])).toEqual([]);
  });

  it('страницы отсортированы даже при обратном порядке входа', () => {
    expect(
      aggregateSources([
        { path: '/m.pdf', page: 9 },
        { path: '/m.pdf', page: 1 },
        { path: '/m.pdf', page: 5 },
      ]),
    ).toEqual([
      { key: '/m.pdf#pages', path: '/m.pdf', pages: [1, 5, 9] },
    ]);
  });
});

describe('extractCitedIndices', () => {
  it('извлекает номера из [N]', () => {
    expect(extractCitedIndices('см. [1] и [3] для подробностей')).toEqual(new Set([1, 3]));
  });

  it('возвращает пустой Set, если ссылок нет', () => {
    expect(extractCitedIndices('просто текст без ссылок').size).toBe(0);
  });

  it('дедуплицирует повторяющиеся номера', () => {
    expect(extractCitedIndices('[2] и снова [2] и [5]')).toEqual(new Set([2, 5]));
  });

  it('не ловит [12] как [1] + [2]', () => {
    expect(extractCitedIndices('см. [12]')).toEqual(new Set([12]));
  });
});
