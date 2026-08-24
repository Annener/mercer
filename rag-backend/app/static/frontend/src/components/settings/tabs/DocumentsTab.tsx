import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  ConfirmModal,
  Field,
  Input,
  Modal,
  Select,
  SelectWrapper,
} from '@/components/ui';
import { api, HttpError } from '@/api/client';
import { useDomainStore, useSettingsStore } from '@/stores';
import { basename } from '@/utils/path';
import { contrastTextColor } from '@/utils/textColor';
import { globalTagsOnly } from '@/utils/tags';
import type {
  Document,
  DomainId,
  TagId,
  TagRead,
} from '@/api/types';
import {
  buildDocsTree,
  collectDirDocs,
  countFilesInDir,
  docFileName,
  matchedAncestors,
  type DirNode,
  type FileNode,
  type TreeNode,
} from './DocumentsTab/tree';
import './DocumentsTab.css';

const POLL_INTERVAL_MS = 3000;
const DEFAULT_TAG_COLOR = '#01696f';

export function DocumentsTab() {
  const selectedRailDomainId = useSettingsStore((s) => s.selectedRailDomainId);
  const setSelectedRailDomain = useSettingsStore((s) => s.setSelectedRailDomain);
  const domains = useDomainStore((s) => s.domains);

  const firstEnabledDomainId = useMemo(
    () => domains.find((d) => d.domain_id !== 'default' && d.enabled !== false)?.domain_id ?? null,
    [domains],
  );

  useEffect(() => {
    if (selectedRailDomainId === null && firstEnabledDomainId) {
      setSelectedRailDomain(firstEnabledDomainId);
    }
  }, [selectedRailDomainId, firstEnabledDomainId, setSelectedRailDomain]);

  const resolved: DomainId | null = useMemo(() => {
    if (selectedRailDomainId) return selectedRailDomainId;
    if (firstEnabledDomainId) return firstEnabledDomainId;
    return null;
  }, [selectedRailDomainId, firstEnabledDomainId]);

  const [filterStatus, setFilterStatus] = useState<string>('');
  const [filterTagId, setFilterTagId] = useState<TagId | ''>('');
  const [search, setSearch] = useState<string>('');
  const [openDirs, setOpenDirs] = useState<Set<string>>(new Set());

  // Modal state — only one of each kind is open at a time.
  const [openDoc, setOpenDoc] = useState<Document | null>(null);
  const [openDir, setOpenDir] = useState<{ name: string; node: DirNode } | null>(null);
  const [openTag, setOpenTag] = useState<TagRead | null>(null);
  const [creatingTag, setCreatingTag] = useState(false);

  const domainId = resolved;

  const documentsQuery = useQuery({
    queryKey: ['documents', domainId, filterStatus, filterTagId],
    queryFn: () =>
      api.getSettingsDocuments({
        domainId,
        status: filterStatus || null,
        tagId: filterTagId || null,
      }),
    enabled: !!domainId,
  });

  const docs = useMemo(() => documentsQuery.data ?? [], [documentsQuery.data]);

  const tagsQuery = useQuery({
    queryKey: ['tags', domainId],
    queryFn: () => api.getTags(domainId),
    enabled: !!domainId,
  });
  const globalTags = useMemo(
    () => (tagsQuery.data ? globalTagsOnly(tagsQuery.data) : []),
    [tagsQuery.data],
  );

  // Filtered docs by search query (client-side, after server-side filters).
  const filteredDocs = useMemo(() => {
    if (!search.trim()) return docs;
    const q = search.toLowerCase();
    return docs.filter((d) => (d.source_path ?? d.path ?? '').toLowerCase().includes(q));
  }, [docs, search]);

  const tree = useMemo(() => buildDocsTree(filteredDocs), [filteredDocs]);
  const isSearchActive = search.trim().length > 0;

  // For directory-toggle persistence across re-renders, we keep `openDirs`.
  // When the user is filtering, we auto-expand ancestors of matched files instead.
  const effectiveOpenDirs = useMemo(() => {
    if (isSearchActive) {
      return matchedAncestors(filteredDocs);
    }
    return openDirs;
  }, [isSearchActive, filteredDocs, openDirs]);

  function toggleDir(dirKey: string): void {
    setOpenDirs((prev) => {
      const next = new Set(prev);
      if (next.has(dirKey)) next.delete(dirKey);
      else next.add(dirKey);
      return next;
    });
  }

  if (!domainId) {
    return (
      <div className="docs-layout">
        <div className="docs-tree p-4">
          <p className="docs-empty">Нет доступных доменов. Создайте домен во вкладке «Домены».</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <IndexerProgressPanel />

      <div className="docs-toolbar">
        <Button
          size="sm"
          variant="primary"
          onClick={() => void documentsQuery.refetch()}
          disabled={documentsQuery.isFetching}
        >
          {documentsQuery.isFetching ? 'Обновление…' : '↻ Обновить'}
        </Button>

        <Button
          size="sm"
          variant="secondary"
          onClick={async () => {
            try {
              await api.runIndexer(domainId);
              void documentsQuery.refetch();
            } catch (e) {
              alert(`Ошибка запуска индексации: ${(e as Error).message}`);
            }
          }}
        >
          ▶ Запустить индексацию
        </Button>

        <Input
          className="docs-toolbar-input"
          placeholder="🔍 поиск по пути…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <SelectWrapper className="docs-toolbar-select">
          <Select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            options={[
              { value: '', label: 'Все статусы' },
              { value: 'indexed', label: 'indexed' },
              { value: 'pending', label: 'pending' },
              { value: 'error', label: 'error' },
            ]}
          />
        </SelectWrapper>

        <SelectWrapper className="docs-toolbar-select">
          <Select
            value={filterTagId}
            onChange={(e) => setFilterTagId((e.target.value as TagId) || '')}
            options={[
              { value: '', label: 'Все теги' },
              ...globalTags.map((t) => ({ value: t.id, label: t.name })),
            ]}
          />
        </SelectWrapper>
      </div>

      <div className="docs-layout">
        <div className="docs-tree">
          {documentsQuery.isLoading ? (
            <p className="docs-empty">Загрузка…</p>
          ) : docs.length === 0 ? (
            <p className="docs-empty">Документов нет</p>
          ) : filteredDocs.length === 0 ? (
            <p className="docs-empty">Нет совпадений для «{search}»</p>
          ) : (
            <table className="docs-tree-table">
              <tbody>
                <TreeRows
                  node={tree}
                  depth={0}
                  effectiveOpenDirs={effectiveOpenDirs}
                  onToggleDir={toggleDir}
                  onOpenDir={(name, node) => setOpenDir({ name, node })}
                  onOpenDoc={(doc) => setOpenDoc(doc)}
                />
              </tbody>
            </table>
          )}
        </div>

        <DomainTagsPanel
          tags={globalTags}
          loading={tagsQuery.isLoading}
          onCreate={() => setCreatingTag(true)}
          onEdit={(tag) => setOpenTag(tag)}
        />
      </div>

      {openDoc && (
        <DocumentModal
          doc={openDoc}
          domainId={domainId}
          onClose={() => setOpenDoc(null)}
        />
      )}

      {openDir && (
        <DirectoryModal
          dirName={openDir.name}
          dirNode={openDir.node}
          globalTags={globalTags}
          onClose={() => setOpenDir(null)}
        />
      )}

      {openTag && (
        <DomainTagModal
          tag={openTag}
          onClose={() => setOpenTag(null)}
        />
      )}

      {creatingTag && (
        <CreateDomainTagModal
          activeDomainId={domainId}
          onClose={() => setCreatingTag(false)}
        />
      )}
    </div>
  );
}

// ============================================================================
// Indexer progress panel
// ============================================================================

function IndexerProgressPanel() {
  const queryClient = useQueryClient();

  const stateQuery = useQuery({
    queryKey: ['systemIndexState'],
    queryFn: () => api.getSystemIndexState(),
    refetchInterval: (q) => {
      const data = q.state.data;
      return data?.has_active ? POLL_INTERVAL_MS : false;
    },
    refetchIntervalInBackground: false,
  });

  // Cancel any active task and refresh list when task completes.
  useEffect(() => {
    const data = stateQuery.data;
    if (!data?.has_active) {
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
    }
  }, [stateQuery.data, queryClient]);

  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => api.cancelIndexTask(taskId),
    onSuccess: () => stateQuery.refetch(),
  });

  const tasks = stateQuery.data?.tasks ?? [];
  if (tasks.length === 0) return null;

  const task = tasks[0]!;
  const status = task.status;
  const isActive = status === 'running';
  const isFinished = status === 'done' || status === 'error' || status === 'cancelled';

  if (isFinished) return null;

  const total = task.files_to_index ?? task.files_total ?? Object.keys(task.files ?? {}).length;
  const done = task.files_done ?? 0;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const filesEntries = Object.entries(task.files ?? {});
  const statusLabel = status === 'running' ? '⚙️ Индексация…' : status;

  return (
    <div className="idx-panel">
      <div className="idx-panel-inner">
        <div className="idx-header">
          <span className="idx-status">{statusLabel}</span>
          {total > 0 && (
            <>
              <span className="idx-count">
                {done} / {total} файлов
              </span>
              <span className="idx-pct">{pct}%</span>
            </>
          )}
          {isActive && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => cancelMutation.mutate(task.task_id)}
              disabled={cancelMutation.isPending}
            >
              ✕ Отмена
            </Button>
          )}
        </div>

        {total > 0 && (
          <div className="idx-bar-track">
            <div
              className={`idx-bar-fill ${isActive ? 'idx-bar-fill--active' : ''}`}
              style={{ width: `${pct}%` }}
            />
          </div>
        )}

        {filesEntries.length > 0 && (
          <div className="idx-files-list">
            {filesEntries.map(([path, f]) => (
              <IndexerFileRow key={path} path={path} stage={f.stage} chunksTotal={f.chunks_total} chunksDone={f.chunks_done} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function IndexerFileRow({
  path,
  stage,
  chunksTotal,
  chunksDone,
}: {
  path: string;
  stage: string;
  chunksTotal: number;
  chunksDone: number;
}) {
  const fp = chunksTotal > 0 ? Math.round((chunksDone / chunksTotal) * 100) : 0;
  const isActive = stage === 'indexing';
  return (
    <div className="idx-file-row">
      <div className="idx-file-header">
        <span className="idx-file-name" title={path}>
          {path.split('/').pop() || path}
        </span>
        <DocStatusBadge status={stage} />
        {chunksTotal > 0 && <span className="idx-file-chunks">{chunksDone}/{chunksTotal} чанков</span>}
      </div>
      {(isActive || chunksTotal > 0) && (
        <div className="idx-bar-track">
          <div
            className={`idx-bar-fill ${isActive ? 'idx-bar-fill--active' : ''}`}
            style={{ width: `${fp}%` }}
          />
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Documents tree
// ============================================================================

interface TreeRowsProps {
  node: DirNode;
  depth: number;
  effectiveOpenDirs: Set<string>;
  onToggleDir: (key: string) => void;
  onOpenDir: (name: string, node: DirNode) => void;
  onOpenDoc: (doc: Document) => void;
}

function TreeRows({
  node,
  depth,
  effectiveOpenDirs,
  onToggleDir,
  onOpenDir,
  onOpenDoc,
}: TreeRowsProps) {
  const entries: Array<[string, TreeNode]> = Object.entries(node.children).sort(
    ([aName, aNode], [bName, bNode]) => {
      if (aNode._isDir !== bNode._isDir) return aNode._isDir ? -1 : 1;
      return aName.localeCompare(bName, 'ru');
    },
  );

  return (
    <>
      {entries.map(([name, child]) => {
        if (child._isDir) {
          return (
            <DirectoryBranch
              key={`dir:${name}`}
              name={name}
              node={child}
              depth={depth}
              effectiveOpenDirs={effectiveOpenDirs}
              onToggleDir={onToggleDir}
              onOpenDir={onOpenDir}
              onOpenDoc={onOpenDoc}
            />
          );
        }
        return <FileRow key={`file:${child.doc.id ?? child.doc.document_id ?? name}`} child={child} depth={depth} onClick={onOpenDoc} />;
      })}
    </>
  );
}

interface DirectoryBranchProps {
  name: string;
  node: DirNode;
  depth: number;
  effectiveOpenDirs: Set<string>;
  onToggleDir: (key: string) => void;
  onOpenDir: (name: string, node: DirNode) => void;
  onOpenDoc: (doc: Document) => void;
}

function DirectoryBranch({
  name,
  node,
  depth,
  effectiveOpenDirs,
  onToggleDir,
  onOpenDir,
  onOpenDoc,
}: DirectoryBranchProps) {
  // Compute stable key from path-traversal context.
  // We use a parent-key prop to disambiguate duplicates.
  const parentKey = useParentKey();
  const dirKey = parentKey ? `${parentKey}/${name}` : name;
  const isOpen = effectiveOpenDirs.has(dirKey);
  const count = countFilesInDir(node);

  function toggle(): void {
    onToggleDir(dirKey);
  }

  return (
    <>
      <tr className="docs-dir-row">
        <td className="docs-dir-cell" style={{ paddingLeft: 8 + depth * 18 }}>
          <span
            className="docs-dir-toggle"
            role="button"
            tabIndex={0}
            aria-label={isOpen ? 'Свернуть' : 'Раскрыть'}
            onClick={(e) => {
              e.stopPropagation();
              toggle();
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                toggle();
              }
            }}
          >
            {isOpen ? '▾' : '▸'}
          </span>
          <span
            className="docs-dir-label"
            onClick={(e) => {
              e.stopPropagation();
              onOpenDir(name, node);
            }}
            title="Управление тегами каталога"
          >
            <span aria-hidden>📁</span>
            <span className="docs-dir-name">{name}</span>
          </span>
          <span className="docs-dir-count">({count})</span>
        </td>
      </tr>
      {isOpen && (
        <DirectoryChildren
          parentKey={dirKey}
          node={node}
          depth={depth + 1}
          effectiveOpenDirs={effectiveOpenDirs}
          onToggleDir={onToggleDir}
          onOpenDir={onOpenDir}
          onOpenDoc={onOpenDoc}
        />
      )}
    </>
  );
}

function DirectoryChildren({
  parentKey,
  node,
  depth,
  effectiveOpenDirs,
  onToggleDir,
  onOpenDir,
  onOpenDoc,
}: {
  parentKey: string;
  node: DirNode;
  depth: number;
  effectiveOpenDirs: Set<string>;
  onToggleDir: (key: string) => void;
  onOpenDir: (name: string, node: DirNode) => void;
  onOpenDoc: (doc: Document) => void;
}) {
  // Use a React Context-like approach via prop drilling since the tree is bounded.
  return (
    <ParentKeyContext.Provider value={parentKey}>
      <TreeRows
        node={node}
        depth={depth}
        effectiveOpenDirs={effectiveOpenDirs}
        onToggleDir={onToggleDir}
        onOpenDir={onOpenDir}
        onOpenDoc={onOpenDoc}
      />
    </ParentKeyContext.Provider>
  );
}

function FileRow({
  child,
  depth,
  onClick,
}: {
  child: FileNode;
  depth: number;
  onClick: (doc: Document) => void;
}) {
  const doc = child.doc;
  const tags = doc.tags ?? [];
  return (
    <tr
      style={{ cursor: 'pointer' }}
      onClick={() => onClick(doc)}
      title={doc.source_path ?? doc.path ?? ''}
    >
      <td style={{ paddingLeft: 8 + depth * 18 }}>
        <div className="docs-file-row">
          <span className="docs-file-name">
            <span aria-hidden>📄</span>
            <span>{docFileName(doc)}</span>
          </span>
          <span className="docs-file-tags">
            {tags.length === 0 ? (
              <span style={{ color: 'var(--color-text-faint, #95a5a6)' }}>—</span>
            ) : (
              tags.slice(0, 4).map((t: TagRead) => (
                <TagBadge key={t.id} tag={t} />
              ))
            )}
            {tags.length > 4 && (
              <span style={{ fontSize: 11, color: 'var(--color-text-muted, #6b7280)' }}>
                +{tags.length - 4}
              </span>
            )}
          </span>
        </div>
      </td>
    </tr>
  );
}

// React context to propagate parent key for nested directories.
const ParentKeyContext = createContext<string | null>(null);

function useParentKey(): string | null {
  return useContext(ParentKeyContext);
}

// ============================================================================
// Document modal (metadata + tag toggle + delete)
// ============================================================================

function DocumentModal({
  doc,
  domainId,
  onClose,
}: {
  doc: Document;
  domainId: DomainId;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const fileName = basename(doc.source_path ?? doc.path ?? doc.id ?? doc.document_id ?? '');

  const tagsQuery = useQuery({
    queryKey: ['tags', domainId],
    queryFn: () => api.getTags(domainId),
    enabled: !!domainId,
  });
  const allTags = useMemo(
    () => (tagsQuery.data ? globalTagsOnly(tagsQuery.data) : []),
    [tagsQuery.data],
  );

  const initialIds = useMemo(
    () => new Set((doc.tags ?? []).map((t) => String(t.id))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [doc.id ?? doc.document_id],
  );
  const [selected, setSelected] = useState<Set<string>>(initialIds);

  function toggleTag(tagId: string): void {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(tagId)) next.delete(tagId);
      else next.add(tagId);
      return next;
    });
  }

  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateDocumentLabels(String(doc.id ?? doc.document_id ?? ''), Array.from(selected)),
    onSuccess: async () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
      onClose();
    },
    onError: (e) => setError(e instanceof HttpError ? e.message : 'Не удалось сохранить теги'),
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteDocumentById(String(doc.id ?? doc.document_id ?? ''), doc.vault_id ?? undefined),
    onSuccess: async () => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
      setConfirmDelete(false);
      onClose();
    },
    onError: (e) => setError(e instanceof HttpError ? e.message : 'Не удалось удалить документ'),
  });

  const meta: Array<[string, string]> = [
    ['ID', String(doc.id ?? doc.document_id ?? '—')],
    ['Vault', String(doc.vault_id ?? '—')],
    ['Путь', String(doc.source_path ?? doc.path ?? '—')],
    ['Статус', String(doc.status ?? '—')],
  ];
  if (doc.created_at) meta.push(['Добавлен', new Date(doc.created_at).toLocaleString('ru')]);

  return (
    <Modal open onClose={onClose} title={fileName || 'Документ'} size="lg">
      <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        <div className="docs-modal-section">
          <div className="docs-modal-section-title">Информация</div>
          <table className="docs-modal-meta">
            <tbody>
              {meta.map(([k, v]) => (
                <tr key={k}>
                  <td className="docs-modal-meta-key">{k}</td>
                  <td className="docs-modal-meta-val">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="docs-modal-section">
          <div className="docs-modal-section-title">Теги</div>
          {tagsQuery.isLoading ? (
            <div className="docs-modal-tags-list">Загрузка…</div>
          ) : allTags.length === 0 ? (
            <div className="docs-modal-tags-list" style={{ color: 'var(--color-text-muted, #6b7280)' }}>
              Тегов нет. Создайте тег в панели справа.
            </div>
          ) : (
            <div className="docs-modal-tags-list">
              {allTags.map((t) => (
                <TagToggleBadge
                  key={t.id}
                  tag={t}
                  on={selected.has(String(t.id))}
                  onToggle={() => toggleTag(String(t.id))}
                />
              ))}
            </div>
          )}

          {error && (
            <div className="docs-dir-status docs-dir-status--error" style={{ marginTop: 8 }}>
              {error}
            </div>
          )}

          <div className="docs-modal-actions">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setConfirmDelete(true)}
              disabled={deleteMutation.isPending || saveMutation.isPending}
            >
              🗑 Удалить
            </Button>
            <div className="docs-modal-actions-right">
              <Button size="sm" variant="ghost" onClick={onClose}>
                Отмена
              </Button>
              <Button
                size="sm"
                variant="primary"
                loading={saveMutation.isPending}
                onClick={() => saveMutation.mutate()}
                disabled={
                  saveMutation.isPending ||
                  Array.from(selected).sort().join(',') ===
                    Array.from(initialIds).sort().join(',')
                }
              >
                Сохранить теги
              </Button>
            </div>
          </div>
        </div>
      </div>

      <ConfirmModal
        open={confirmDelete}
        title="Удалить документ"
        message={
          <>
            Удалить документ <span style={{ fontWeight: 600 }}>{fileName || doc.id}</span>?
            Действие необратимо.
          </>
        }
        pending={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate()}
        onClose={() => setConfirmDelete(false)}
      />
    </Modal>
  );
}

// ============================================================================
// Directory modal (bulk assign / remove tags)
// ============================================================================

function DirectoryModal({
  dirName,
  dirNode,
  globalTags,
  onClose,
}: {
  dirName: string;
  dirNode: DirNode;
  globalTags: TagRead[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const allDocs = useMemo(() => collectDirDocs(dirNode), [dirNode]);

  // Compute current per-tag counts in this directory.
  const tagDocCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const d of allDocs) {
      for (const t of d.tags ?? []) {
        const tid = String(t.id);
        counts[tid] = (counts[tid] ?? 0) + 1;
      }
    }
    return counts;
  }, [allDocs]);

  // Tags present on at least one file in the directory.
  const presentTags = useMemo(
    () =>
      globalTags.filter((t) => (tagDocCounts[String(t.id)] ?? 0) > 0),
    [globalTags, tagDocCounts],
  );

  const [statusAssign, setStatusAssign] = useState<{ kind: 'loading' | 'ok' | 'error'; text: string } | null>(null);
  const [statusRemove, setStatusRemove] = useState<{ kind: 'loading' | 'ok' | 'error'; text: string } | null>(null);

  const applyMutation = useMutation({
    mutationFn: async ({
      tagId,
      mode,
    }: {
      tagId: string;
      mode: 'assign' | 'remove';
    }) => {
      const errors: string[] = [];
      for (const d of allDocs) {
        const docId = String(d.id ?? d.document_id ?? '');
        const docTags: TagRead[] = d.tags ?? [];
        const current: Set<string> = new Set(docTags.map((t: TagRead) => String(t.id)));
        if (mode === 'assign') {
          if (current.has(tagId)) continue;
          current.add(tagId);
        } else {
          if (!current.has(tagId)) continue;
          current.delete(tagId);
        }
        try {
          await api.updateDocumentLabels(docId, Array.from(current));
        } catch {
          errors.push(d.source_path ?? d.path ?? docId);
        }
      }
      if (errors.length > 0) throw new Error(`Не удалось обновить ${errors.length} файл(ов):\n${errors.join('\n')}`);
    },
    onSuccess: (_d: unknown, vars: { tagId: string; mode: 'assign' | 'remove' }) => {
      const setStatus = vars.mode === 'assign' ? setStatusAssign : setStatusRemove;
      setStatus({ kind: 'ok', text: '✅ Готово' });
      setTimeout(() => setStatus(null), 2000);
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (err: Error, vars: { tagId: string; mode: 'assign' | 'remove' }) => {
      const setStatus = vars.mode === 'assign' ? setStatusAssign : setStatusRemove;
      setStatus({ kind: 'error', text: err.message });
    },
  });

  return (
    <Modal open onClose={onClose} title={`📁 ${dirName} — ${allDocs.length} файл(ов)`} size="lg">
      <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        <div className="docs-modal-section">
          <div className="docs-modal-section-title">Назначить тег на все файлы</div>
          {globalTags.length === 0 ? (
            <div className="docs-modal-tags-list" style={{ color: 'var(--color-text-muted, #6b7280)' }}>
              Нет тегов в домене
            </div>
          ) : (
            <div className="docs-dir-tag-list">
              {globalTags.map((t) => {
                const tid = String(t.id);
                const allHave = tagDocCounts[tid] === allDocs.length;
                return (
                  <TagToggleBadge
                    key={`assign-${tid}`}
                    tag={t}
                    on={allHave}
                    onToggle={() => applyMutation.mutate({ tagId: tid, mode: 'assign' })}
                    disabled={allHave || applyMutation.isPending}
                  />
                );
              })}
            </div>
          )}
          {statusAssign && (
            <div className={`docs-dir-status docs-dir-status--${statusAssign.kind}`}>{statusAssign.text}</div>
          )}
        </div>

        <div className="docs-modal-section">
          <div className="docs-modal-section-title">Снять тег со всех файлов</div>
          {presentTags.length === 0 ? (
            <div className="docs-modal-tags-list" style={{ color: 'var(--color-text-muted, #6b7280)' }}>
              Нет тегов ни на одном файле
            </div>
          ) : (
            <div className="docs-dir-tag-list">
              {presentTags.map((t) => {
                const tid = String(t.id);
                return (
                  <TagToggleBadge
                    key={`remove-${tid}`}
                    tag={t}
                    on={true}
                    onToggle={() => applyMutation.mutate({ tagId: tid, mode: 'remove' })}
                    disabled={applyMutation.isPending}
                  />
                );
              })}
            </div>
          )}
          {statusRemove && (
            <div className={`docs-dir-status docs-dir-status--${statusRemove.kind}`}>{statusRemove.text}</div>
          )}
        </div>
      </div>
      <div style={{ padding: 12, borderTop: '1px solid var(--color-border, #e5e7eb)', textAlign: 'right' }}>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Закрыть
        </Button>
      </div>
    </Modal>
  );
}

// ============================================================================
// Domain tags panel (right side)
// ============================================================================

function DomainTagsPanel({
  tags,
  loading,
  onCreate,
  onEdit,
}: {
  tags: TagRead[];
  loading: boolean;
  onCreate: () => void;
  onEdit: (tag: TagRead) => void;
}) {
  return (
    <aside className="docs-tags-panel">
      <div className="docs-tags-header">Теги домена</div>
      <div className="docs-tags-list">
        {loading ? (
          <div className="docs-tag-empty">Загрузка…</div>
        ) : tags.length === 0 ? (
          <div className="docs-tag-empty">Тегов нет</div>
        ) : (
          tags.map((t) => (
            <div className="docs-tag-item" key={t.id}>
              <button
                type="button"
                className="docs-tag-item-tag"
                onClick={() => onEdit(t)}
                title="Редактировать тег"
              >
                <TagBadge tag={t} />
              </button>
            </div>
          ))
        )}
      </div>
      <div className="docs-tags-footer">
        <Button size="sm" variant="primary" onClick={onCreate} className="w-full">
          + Новый тег
        </Button>
      </div>
    </aside>
  );
}

// ============================================================================
// Tag CRUD modals
// ============================================================================

function DomainTagModal({ tag, onClose }: { tag: TagRead; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(tag.name);
  const [color, setColor] = useState(tag.color || DEFAULT_TAG_COLOR);
  const [error, setError] = useState<string | null>(null);

  const updateMutation = useMutation({
    mutationFn: () => api.updateTag(tag.id, { name: name.trim(), color }),
    onSuccess: async () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['tags'] });
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
      onClose();
    },
    onError: (e) => setError(e instanceof HttpError ? e.message : 'Не удалось сохранить тег'),
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteTag(tag.id),
    onSuccess: async () => {
      void queryClient.invalidateQueries({ queryKey: ['tags'] });
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
      onClose();
    },
    onError: (e) => setError(e instanceof HttpError ? e.message : 'Не удалось удалить тег'),
  });

  const previewColor = color || DEFAULT_TAG_COLOR;
  const previewText = name.trim() || 'Тег';

  return (
    <Modal open onClose={onClose} title="Тег домена" size="sm">
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Название">
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>

        <Field label="Цвет">
          <div className="docs-tag-form-row">
            <input
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              style={{ width: 36, height: 28, cursor: 'pointer', border: '1px solid var(--color-border, #e5e7eb)', borderRadius: 4 }}
            />
            <span
              className="docs-tag-preview"
              style={tagStyle(previewColor)}
              title="Предпросмотр"
            >
              {previewText}
            </span>
          </div>
        </Field>

        {error && (
          <div className="docs-dir-status docs-dir-status--error">{error}</div>
        )}

        <div className="docs-modal-actions">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              if (confirm(`Удалить тег «${tag.name}»?`)) deleteMutation.mutate();
            }}
            disabled={deleteMutation.isPending || updateMutation.isPending}
          >
            Удалить
          </Button>
          <div className="docs-modal-actions-right">
            <Button size="sm" variant="ghost" onClick={onClose}>
              Отмена
            </Button>
            <Button
              size="sm"
              variant="primary"
              loading={updateMutation.isPending}
              onClick={() => updateMutation.mutate()}
              disabled={!name.trim() || updateMutation.isPending}
            >
              Сохранить
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function CreateDomainTagModal({
  activeDomainId,
  onClose,
}: {
  activeDomainId: DomainId;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const domains = useDomainStore((s) => s.domains);
  const [name, setName] = useState('');
  const [color, setColor] = useState(DEFAULT_TAG_COLOR);
  const [domainId, setDomainId] = useState<string>(activeDomainId);
  const [error, setError] = useState<string | null>(null);

  const activeDomains = useMemo(
    () => domains.filter((d) => d.domain_id !== 'default' && d.enabled !== false),
    [domains],
  );

  const createMutation = useMutation({
    mutationFn: () =>
      api.createTag({ name: name.trim(), color, domain_id: domainId }),
    onSuccess: async () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['tags'] });
      onClose();
    },
    onError: (e) =>
      setError(e instanceof HttpError ? e.message : 'Не удалось создать тег'),
  });

  const previewText = name.trim() || 'Тег';

  return (
    <Modal open onClose={onClose} title="Новый тег" size="sm">
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Field label="Название">
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="Название тега" />
        </Field>

        <Field label="Цвет">
          <div className="docs-tag-form-row">
            <input
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              style={{ width: 36, height: 28, cursor: 'pointer', border: '1px solid var(--color-border, #e5e7eb)', borderRadius: 4 }}
            />
            <span className="docs-tag-preview" style={tagStyle(color)}>
              {previewText}
            </span>
          </div>
        </Field>

        <SelectWrapper label="Домен">
          <Select
            value={domainId}
            onChange={(e) => setDomainId(e.target.value)}
            options={activeDomains.map((d) => ({
              value: d.domain_id,
              label: d.display_name || d.domain_id,
            }))}
          />
        </SelectWrapper>

        {error && <div className="docs-dir-status docs-dir-status--error">{error}</div>}

        <div className="docs-modal-actions">
          <div className="docs-modal-actions-right">
            <Button size="sm" variant="ghost" onClick={onClose}>
              Отмена
            </Button>
            <Button
              size="sm"
              variant="primary"
              loading={createMutation.isPending}
              onClick={() => createMutation.mutate()}
              disabled={!name.trim() || !domainId || createMutation.isPending}
            >
              Создать
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

// ============================================================================
// Shared bits
// ============================================================================

function TagBadge({ tag }: { tag: TagRead }) {
  const color = tag.color || DEFAULT_TAG_COLOR;
  const style = tagStyle(color);
  return (
    <span className="docs-tag-preview" style={style}>
      {tag.name}
    </span>
  );
}

function TagToggleBadge({
  tag,
  on,
  onToggle,
  disabled,
}: {
  tag: TagRead;
  on: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  const color = tag.color || DEFAULT_TAG_COLOR;
  return (
    <button
      type="button"
      className={`docs-modal-tag-toggle ${on ? 'docs-modal-tag-toggle--on' : 'docs-modal-tag-toggle--off'}`}
      style={on ? tagStyle(color) : undefined}
      onClick={onToggle}
      disabled={disabled}
    >
      {tag.name}
    </button>
  );
}

function DocStatusBadge({ status }: { status?: string }) {
  const s = status || 'unknown';
  return <span className={`docs-doc-status-badge docs-doc-status-badge--${s}`}>{s}</span>;
}

function tagStyle(color: string): CSSProperties {
  const textColor = contrastTextColor(color);
  return {
    background: color,
    color: textColor,
    borderColor: color,
  };
}

// Re-export from tree (used by tests). TreeNode import kept here for clarity.
export type { TreeNode };