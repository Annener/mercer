# Этап 6 — Фронтенд: настройки (Settings → секция «Индексация»)

## Цель

Добавить в UI управление `watchdog_auto_index_extensions`: админ видит чекбоксы
по расширениям и сохраняет при нажатии «Сохранить».

## Контекст из кодовой базы

Уточните перед реализацией через MCP:

```
frontend/src/views/SettingsView.*
frontend/src/api/*.js (или *.ts)
```

Фронтенд использует `fetch` или axios-централизованный client, узнайте до реализации.

## Что нужно сделать

### UX-логика

```
Секция «Индексация»:
  Заголовок: «Авто-индексация при изменении файлов»
  Подзаголовок: «Файлы этих типов будут переиндексированы автоматически»
  [✓] .md
  [✓] .pdf
  [ ] .docx
  [ ] .txt
  Ввод своего расширения: [    ] + [Добавить]
  [Сохранить]
```

Предопределённый список расширений: `.md`, `.pdf`, `.docx`, `.txt`, `.rst`, `.html`.
Lookup построен статически в компоненте, дополнительно можно ввести своё.

### API-слой

Создайте `frontend/src/api/watchdogSettings.js` (или `.ts`):

```js
const BASE = '/api/v1/settings/watchdog';

export async function getWatchdogSettings() {
  const res = await fetch(BASE);
  if (!res.ok) throw new Error('Failed to load watchdog settings');
  return res.json(); // { auto_index_extensions: string[] }
}

export async function saveWatchdogSettings(extensions) {
  const res = await fetch(BASE, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auto_index_extensions: extensions }),
  });
  if (!res.ok) throw new Error('Failed to save watchdog settings');
  return res.json();
}
```

### Компонент `WatchdogSettings`

Создайте `frontend/src/components/WatchdogSettings.vue`
(или `.jsx`/`.tsx` — смотрите какой фреймворк использует проект):

```vue
<script setup>
import { ref, onMounted } from 'vue';
import { getWatchdogSettings, saveWatchdogSettings } from '@/api/watchdogSettings';

const KNOWN_EXTENSIONS = ['.md', '.pdf', '.docx', '.txt', '.rst', '.html'];

const selected = ref(new Set());
const customInput = ref('');
const saving = ref(false);
const error = ref('');
const success = ref(false);

onMounted(async () => {
  try {
    const data = await getWatchdogSettings();
    selected.value = new Set(data.auto_index_extensions);
  } catch (e) {
    error.value = 'Не удалось загрузить настройки';
  }
});

function toggle(ext) {
  if (selected.value.has(ext)) selected.value.delete(ext);
  else selected.value.add(ext);
}

function addCustom() {
  const ext = customInput.value.trim();
  if (!ext.startsWith('.')) {
    error.value = 'Расширение должно начинаться с "."';
    return;
  }
  selected.value.add(ext);
  customInput.value = '';
  error.value = '';
}

async function save() {
  saving.value = true;
  error.value = '';
  success.value = false;
  try {
    await saveWatchdogSettings([...selected.value]);
    success.value = true;
    setTimeout(() => { success.value = false; }, 3000);
  } catch (e) {
    error.value = 'Не удалось сохранить настройки';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="watchdog-settings">
    <h3>Авто-индексация при изменении файлов</h3>
    <p class="hint">Файлы этих типов будут переиндексированы автоматически</p>

    <div class="ext-list">
      <label v-for="ext in KNOWN_EXTENSIONS" :key="ext">
        <input type="checkbox" :checked="selected.has(ext)" @change="toggle(ext)" />
        {{ ext }}
      </label>
    </div>

    <div class="custom-input">
      <input
        v-model="customInput"
        placeholder=".epub"
        @keyup.enter="addCustom"
      />
      <button type="button" @click="addCustom">Добавить</button>
    </div>

    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="success" class="success">Настройки сохранены</div>

    <button :disabled="saving" @click="save">
      {{ saving ? 'Сохранение…' : 'Сохранить' }}
    </button>
  </section>
</template>
```

### Включение в `SettingsView`

```vue
<WatchdogSettings />
```
в секции «Индексация».

## Файлы для создания / изменения

| Файл | Действие |
|---|---|
| `frontend/src/api/watchdogSettings.js` | Создать |
| `frontend/src/components/WatchdogSettings.vue` | Создать |
| `frontend/src/views/SettingsView.vue` | `+<WatchdogSettings />` в секции индексации |

## Критерий готовности

- [ ] При открытии вкладки читается `GET /api/v1/settings/watchdog`, чекбоксы отображают текущие значения
- [ ] При «Сохранить» отправляется `PATCH /api/v1/settings/watchdog` с выбранными расширениями
- [ ] Валидация: нельзя добавить расширение без точки
- [ ] Сообщение «Настройки сохранены» после успешного сохранения
- [ ] `STATUS.md` обновлён: этап 6 → ✅
