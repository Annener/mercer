import { describe, expect, it } from 'vitest';
import type { TagRead } from '@/api/types';
import { flattenTags, globalTagsOnly, isTagsGrouped, tagDisplayName } from './tags';

function makeTag(overrides: Partial<TagRead>): TagRead {
  return {
    id: overrides.id ?? 'tag-1',
    name: overrides.name ?? 'Tag',
    domain_id: overrides.domain_id ?? 'domain-1',
    campaign_id: overrides.campaign_id ?? null,
    color: overrides.color ?? null,
    ...overrides,
  };
}

describe('utils/tags.isTagsGrouped', () => {
  it('returns true for grouped shape', () => {
    expect(isTagsGrouped({ global_tags: [], by_campaign: {} })).toBe(true);
  });

  it('returns false for flat array', () => {
    expect(isTagsGrouped([])).toBe(false);
  });
});

describe('utils/tags.globalTagsOnly', () => {
  it('on flat array keeps only tags with campaign_id == null', () => {
    const flat = [
      makeTag({ id: 'g1', name: 'G1', campaign_id: null }),
      makeTag({ id: 'c1', name: 'C1', campaign_id: 'campaign-1' }),
    ];
    expect(globalTagsOnly(flat)).toEqual([expect.objectContaining({ id: 'g1' })]);
  });

  it('on grouped shape returns only global_tags', () => {
    const grouped = {
      global_tags: [makeTag({ id: 'g1' })],
      by_campaign: { 'campaign-1': [makeTag({ id: 'c1', campaign_id: 'campaign-1' })] },
    };
    expect(globalTagsOnly(grouped)).toEqual([expect.objectContaining({ id: 'g1' })]);
  });
});

describe('utils/tags.flattenTags', () => {
  it('on flat array returns it as-is', () => {
    const flat = [makeTag({ id: 'g1' }), makeTag({ id: 'c1', campaign_id: 'campaign-1' })];
    expect(flattenTags(flat)).toBe(flat);
  });

  it('on grouped shape merges global + per-campaign without duplicates', () => {
    const grouped = {
      global_tags: [makeTag({ id: 'g1', name: 'G1' })],
      by_campaign: {
        'campaign-1': [
          makeTag({ id: 'g1', name: 'Dup' }),
          makeTag({ id: 'c1', name: 'C1', campaign_id: 'campaign-1' }),
        ],
        'campaign-2': [makeTag({ id: 'c2', name: 'C2', campaign_id: 'campaign-2' })],
      },
    };
    const flat = flattenTags(grouped);
    expect(flat).toHaveLength(3);
    expect(flat.map((t) => t.id).sort()).toEqual(['c1', 'c2', 'g1']);
  });
});

describe('utils/tags.tagDisplayName', () => {
  it('returns plain name for global tags', () => {
    expect(tagDisplayName(makeTag({ id: 'g1', name: 'Hero' }))).toBe('Hero');
  });

  it('prefixes campaign display_name for campaign tags', () => {
    const campaignsById = new Map([
      ['campaign-1', { id: 'campaign-1', display_name: 'Q4 Launch', name: '' }],
    ]);
    expect(
      tagDisplayName(makeTag({ id: 'c1', name: 'Draft', campaign_id: 'campaign-1' }), campaignsById),
    ).toBe('Q4 Launch • Draft');
  });

  it('falls back to «Кампания» when campaign not found in map', () => {
    expect(tagDisplayName(makeTag({ id: 'c1', name: 'Draft', campaign_id: 'campaign-x' }))).toBe(
      'Кампания • Draft',
    );
  });

  it('falls back to name when display_name missing', () => {
    const campaignsById = new Map([
      ['campaign-1', { id: 'campaign-1', display_name: null, name: 'fallback' }],
    ]);
    expect(
      tagDisplayName(makeTag({ id: 'c1', name: 'Draft', campaign_id: 'campaign-1' }), campaignsById),
    ).toBe('fallback • Draft');
  });
});
