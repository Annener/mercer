/**
 * Чистые функции для построения и обхода дерева файлов на вкладке «Документы».
 * Портировано из старой реализации tab-documents.js (@HEAD, commit e3188a9).
 */

import type { Document } from '@/api/types';

export interface DirNode {
  _isDir: true;
  children: Record<string, TreeNode>;
}

export interface FileNode {
  _isDir: false;
  doc: Document;
}

export type TreeNode = DirNode | FileNode;

const ROOT = 'PLACEHOLDER_ROOT';

function docPath(doc: Document): string {
  return doc.source_path || doc.path || String(doc.id ?? doc.document_id ?? '');
}

/**
 * Строит вложенное дерево директорий из плоского списка документов.
 * Узел верхнего уровня — фиктивный `_root` для удобства рекурсии.
 */
export function buildDocsTree(docs: Document[]): DirNode {
  const root: DirNode = { _isDir: true, children: {} };
  for (const doc of docs) {
    const fullPath = docPath(doc);
    const parts = fullPath.split('/').filter(Boolean);
    let node: DirNode = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const seg = parts[i]!;
      const existing = node.children[seg];
      if (!existing || !existing._isDir) {
        const dir: DirNode = { _isDir: true, children: {} };
        node.children[seg] = dir;
        node = dir;
      } else {
        node = existing;
      }
    }
    const fileName = parts[parts.length - 1] || String(doc.id ?? doc.document_id ?? ROOT);
    node.children[fileName] = { _isDir: false, doc };
  }
  return root;
}

/**
 * Рекурсивно собирает все документы в поддереве (включая вложенные директории).
 */
export function collectDirDocs(node: TreeNode): Document[] {
  const result: Document[] = [];
  if (!node._isDir) {
    result.push(node.doc);
    return result;
  }
  for (const child of Object.values(node.children)) {
    result.push(...collectDirDocs(child));
  }
  return result;
}

/**
 * Количество файлов в поддереве (только документы, директории не считаются).
 */
export function countFilesInDir(node: DirNode): number {
  let n = 0;
  for (const child of Object.values(node.children)) {
    if (child._isDir) n += countFilesInDir(child);
    else n += 1;
  }
  return n;
}

/**
 * Возвращает Set путей директорий-предков совпадающих файлов.
 * Используется для авто-раскрытия предков при поиске.
 */
export function matchedAncestors(docs: Document[]): Set<string> {
  const set = new Set<string>();
  for (const doc of docs) {
    const parts = docPath(doc).split('/').filter(Boolean);
    let prefix = '';
    for (let i = 0; i < parts.length - 1; i++) {
      prefix = prefix ? `${prefix}/${parts[i]}` : parts[i]!;
      set.add(prefix);
    }
  }
  return set;
}

/**
 * Имя файла из doc.source_path (последний сегмент).
 */
export function docFileName(doc: Document): string {
  const full = docPath(doc);
  const parts = full.split('/').filter(Boolean);
  return parts[parts.length - 1] || String(doc.id ?? doc.document_id ?? '');
}