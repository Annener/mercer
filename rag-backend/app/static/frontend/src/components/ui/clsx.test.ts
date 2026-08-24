import { describe, it, expect } from 'vitest';
import { clsx } from '@/components/ui/clsx';

describe('clsx', () => {
  it('joins truthy strings', () => {
    expect(clsx('a', 'b', 'c')).toBe('a b c');
  });

  it('filters out falsy values', () => {
    expect(clsx('a', false, null, undefined, '', 'b')).toBe('a b');
  });

  it('handles objects', () => {
    expect(clsx('a', { b: true, c: false })).toBe('a b');
  });

  it('coerces numbers', () => {
    expect(clsx(0, 1, 2)).toBe('1 2');
  });

  it('returns empty string when no truthy inputs', () => {
    expect(clsx(false, null, undefined)).toBe('');
  });
});