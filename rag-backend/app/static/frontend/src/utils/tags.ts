/**
 * Helpers для работы с результатом /api/settings/tags.
 * Бэкенд возвращает {global_tags, by_campaign}, но старые маршруты
 * (campaign-level) могут вернуть плоский TagRead[] — обрабатываем оба.
 */

import type { TagRead, TagsGrouped } from '@/api/types';

export function isTagsGrouped(v: TagRead[] | TagsGrouped): v is TagsGrouped {
  return !Array.isArray(v);
}

/** Плоский список тегов домена: глобальные + campaign-level, без ли дублей по id. */
export function flattenTags(v: TagRead[] | TagsGrouped): TagRead[] {
  if (!isTagsGrouped(v)) return v;
  const seen = new Set<string>();
  const out: TagRead[] = [];
  for (const t of v.global_tags) {
    if (!seen.has(t.id)) {
      seen.add(t.id);
      out.push(t);
    }
  }
  for (const list of Object.values(v.by_campaign)) {
    for (const t of list) {
      if (!seen.has(t.id)) {
        seen.add(t.id);
        out.push(t);
      }
    }
  }
  return out;
}

/** Только глобальные теги домена (campaign_id === null). */
export function globalTagsOnly(v: TagRead[] | TagsGrouped): TagRead[] {
  const flat = isTagsGrouped(v) ? v.global_tags : v.filter((t) => t.campaign_id == null);
  return flat;
}