# Этап 7 — Фронтенд: баннер pending-files в чате

## Цель

Если в активном vault есть файлы со статусом `pending` — показать баннер
с кнопкой «Запустить индексацию». Polling каждые 30 секунд.

## Контекст из кодовой базы

Perед реализацией уточните через MCP:
- Как в чат-компоненте сейчас решается получение `vault_id` (через props / store)
- Как уже запускается индексация (есть ли `POST /api/v1/vaults/{id}/index` или `rag-indexer` API)

```
frontend/src/views/ChatView.*
frontend/src/api/indexer.js (или *.ts)
```

## Что нужно сделать

### API-слой

Добавить в `frontend/src/api/indexer.js` (createIfAbsent):

```js
/**
 * Returns list of pending-files for a vault.
 * @param {string} vaultId
 * @returns {Promise<{vault_id: string, pending_files: string[], total: number}>}
 */
export async function getPendingFiles(vaultId) {
  const res = await fetch(`/api/v1/vaults/${vaultId}/pending-files`);
  if (!res.ok) throw new Error('Failed to fetch pending files');
  return res.json();
}
```

### Компонент `PendingFilesBanner.vue`

```vue
<script setup>
import { ref, watch, onUnmounted } from 'vue';
import { getPendingFiles } from '@/api/indexer';

const props = defineProps({
  vaultId: { type: String, required: true },
  onStartIndex: { type: Function, required: true }, // () => Promise<void>
});

const pendingCount = ref(0);
const starting = ref(false);
const POLL_MS = 30_000;
let timer = null;

async function poll() {
  if (!props.vaultId) return;
  try {
    const data = await getPendingFiles(props.vaultId);
    pendingCount.value = data.total;
  } catch {
    // сеть недоступна — игнорируем
  }
}

function startPolling() {
  clearInterval(timer);
  poll(); // немедленный первый запрос
  timer = setInterval(poll, POLL_MS);
}

async function handleStart() {
  starting.value = true;
  try {
    await props.onStartIndex();
    pendingCount.value = 0;
  } finally {
    starting.value = false;
    poll();
  }
}

watch(() => props.vaultId, startPolling, { immediate: true });
onUnmounted(() => clearInterval(timer));
</script>

<template>
  <div v-if="pendingCount > 0" class="pending-banner">
    <span>› {{ pendingCount }} файл {{ pendingCount === 1 ? 'изменён' : 'изменены' }} и ожидают индексации</span>
    <button :disabled="starting" @click="handleStart">
      {{ starting ? 'Запуск…' : 'Запустить индексацию' }}
    </button>
  </div>
</template>

<style scoped>
.pending-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: #fff8e1;
  border-left: 4px solid #f59e0b;
  border-radius: 4px;
  font-size: 0.9rem;
}
.pending-banner button {
  padding: 4px 12px;
  background: #f59e0b;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
.pending-banner button:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
```

### Включение в `ChatView`

```vue
<PendingFilesBanner
  :vault-id="currentVaultId"
  :on-start-index="handleStartIndex"
/>
```

Где `handleStartIndex` вызывает существующий API запуска индексации во васшем проекте.

## Файлы для создания / изменения

| Файл | Действие |
|---|---|
| `frontend/src/components/PendingFilesBanner.vue` | Создать |
| `frontend/src/api/indexer.js` | `+getPendingFiles(vaultId)` |
| `frontend/src/views/ChatView.vue` | `+<PendingFilesBanner .../>` |

## Критерий готовности

- [ ] Баннер виден только при `pendingCount > 0`
- [ ] Polling перестаёт при `onUnmounted`
- [ ] При смене `vaultId` polling перезапускается
- [ ] Кнопка заблокирована во время запуска
- [ ] `STATUS.md` обновлён: этап 7 → ✅
