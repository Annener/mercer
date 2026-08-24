import { describe, it, expect } from 'vitest';
import { HttpError } from '@/api/http';

describe('HttpError', () => {
  it('formats string detail', () => {
    const e = new HttpError(409, 'source_snapshot_stale', 'Conflict');
    expect(e.message).toBe('source_snapshot_stale');
    expect(e.status).toBe(409);
    expect(e.detail).toBe('source_snapshot_stale');
    expect(e.isCode('source_snapshot_stale')).toBe(true);
  });

  it('handles object detail with code', () => {
    const detail = { code: 'snapshot_stale', stale_documents: ['doc1', 'doc2'] };
    const e = new HttpError(409, detail, 'Conflict');
    expect(e.isCode('snapshot_stale')).toBe(true);
    expect(e.isCode('other')).toBe(false);
  });

  it('returns false for isCode when detail is null', () => {
    const e = new HttpError(500, null, 'Internal');
    expect(e.isCode('foo')).toBe(false);
  });

  it('falls back when detail is empty string', () => {
    const e = new HttpError(500, '', 'Internal Error');
    expect(e.message).toBe('Internal Error');
  });
});