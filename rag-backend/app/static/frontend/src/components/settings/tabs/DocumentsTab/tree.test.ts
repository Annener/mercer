import { describe, expect, it } from 'vitest';
import type { Document } from '@/api/types';
import {
  buildDocsTree,
  collectDirDocs,
  countFilesInDir,
  docFileName,
  matchedAncestors,
} from './tree';

function makeDoc(overrides: Partial<Document>): Document {
  return {
    id: overrides.id ?? 'doc-1',
    document_id: overrides.document_id ?? overrides.id ?? 'doc-1',
    vault_id: overrides.vault_id ?? 'v',
    source_path: overrides.source_path,
    path: overrides.path,
    status: overrides.status ?? 'indexed',
    tags: overrides.tags ?? [],
    ...overrides,
  } as Document;
}

describe('buildDocsTree', () => {
  it('returns empty root for empty list', () => {
    const tree = buildDocsTree([]);
    expect(tree._isDir).toBe(true);
    expect(Object.keys(tree.children)).toHaveLength(0);
  });

  it('places root file when path has no slashes', () => {
    const tree = buildDocsTree([makeDoc({ id: '1', source_path: 'readme.md' })]);
    expect(Object.keys(tree.children)).toEqual(['readme.md']);
    const node = tree.children['readme.md']!;
    expect(node._isDir).toBe(false);
  });

  it('builds nested directory hierarchy', () => {
    const docs = [
      makeDoc({ id: '1', source_path: 'docs/spec.md' }),
      makeDoc({ id: '2', source_path: 'docs/sub/note.md' }),
      makeDoc({ id: '3', source_path: 'docs/sub/deep/x.md' }),
    ];
    const tree = buildDocsTree(docs);
    expect(Object.keys(tree.children)).toEqual(['docs']);
    const docsNode = tree.children['docs']!;
    expect(docsNode._isDir).toBe(true);
    if (!docsNode._isDir) return;

    expect(Object.keys(docsNode.children)).toEqual(['spec.md', 'sub']);
    const subNode = docsNode.children['sub']!;
    expect(subNode._isDir).toBe(true);
    if (!subNode._isDir) return;

    expect(Object.keys(subNode.children)).toEqual(['note.md', 'deep']);
  });

  it('uses doc.id fallback when path is missing', () => {
    const tree = buildDocsTree([makeDoc({ id: 'abc', source_path: '' })]);
    expect(Object.keys(tree.children)).toEqual(['abc']);
  });
});

describe('collectDirDocs', () => {
  it('collects all docs from nested subtrees', () => {
    const docs = [
      makeDoc({ id: '1', source_path: 'a/1.md' }),
      makeDoc({ id: '2', source_path: 'a/b/2.md' }),
      makeDoc({ id: '3', source_path: 'a/b/c/3.md' }),
    ];
    const tree = buildDocsTree(docs);
    const collected = collectDirDocs(tree);
    expect(collected.map((d) => d.id).sort()).toEqual(['1', '2', '3']);
  });

  it('returns single doc when called on a file node', () => {
    const docs = [makeDoc({ id: '1', source_path: 'a/1.md' })];
    const tree = buildDocsTree(docs);
    const aNode = tree.children['a']!;
    const fileNode = aNode._isDir ? aNode.children['1.md']! : null;
    if (!fileNode || fileNode._isDir) throw new Error('expected file node');
    expect(collectDirDocs(fileNode).map((d) => d.id)).toEqual(['1']);
  });
});

describe('countFilesInDir', () => {
  it('counts files recursively but not directories', () => {
    const docs = [
      makeDoc({ id: '1', source_path: 'a/1.md' }),
      makeDoc({ id: '2', source_path: 'a/b/2.md' }),
      makeDoc({ id: '3', source_path: 'a/b/3.md' }),
    ];
    const tree = buildDocsTree(docs);
    expect(countFilesInDir(tree)).toBe(3);
    const aNode = tree.children['a']!;
    if (!aNode._isDir) throw new Error('expected dir');
    expect(countFilesInDir(aNode)).toBe(3);
    const bNode = aNode.children['b']!;
    if (!bNode._isDir) throw new Error('expected dir');
    expect(countFilesInDir(bNode)).toBe(2);
  });
});

describe('matchedAncestors', () => {
  it('returns ancestor directories without leaf filename', () => {
    const docs = [
      makeDoc({ id: '1', source_path: 'a/b/c/file.md' }),
      makeDoc({ id: '2', source_path: 'a/other.md' }),
    ];
    const ancestors = matchedAncestors(docs);
    expect(ancestors.has('a')).toBe(true);
    expect(ancestors.has('a/b')).toBe(true);
    expect(ancestors.has('a/b/c')).toBe(true);
    expect(ancestors.has('a/b/c/file.md')).toBe(false);
    expect(ancestors.has('a/other.md')).toBe(false);
  });

  it('returns empty set for root-level files', () => {
    const docs = [makeDoc({ id: '1', source_path: 'file.md' })];
    expect(matchedAncestors(docs).size).toBe(0);
  });
});

describe('docFileName', () => {
  it('returns last segment of path', () => {
    expect(docFileName(makeDoc({ id: '1', source_path: 'a/b/c.md' }))).toBe('c.md');
    expect(docFileName(makeDoc({ id: '1', source_path: 'plain.md' }))).toBe('plain.md');
  });

  it('falls back to id when path is missing', () => {
    expect(docFileName(makeDoc({ id: 'xyz', source_path: '' }))).toBe('xyz');
  });
});