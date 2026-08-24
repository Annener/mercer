/**
 * Безопасный wrapper над localStorage. Падает в in-memory storage
 * если доступ запрещён (приватный режим, тесты).
 */

let memory: Record<string, string> = {};

const storage = (() => {
  try {
    localStorage.setItem('__mercer_test__', '1');
    localStorage.removeItem('__mercer_test__');
    return {
      getItem: (k: string) => localStorage.getItem(k),
      setItem: (k: string, v: string) => localStorage.setItem(k, v),
      removeItem: (k: string) => localStorage.removeItem(k),
    };
  } catch {
    return {
      getItem: (k: string) => (k in memory ? memory[k]! : null),
      setItem: (k: string, v: string) => {
        memory[k] = String(v);
      },
      removeItem: (k: string) => {
        delete memory[k];
      },
    };
  }
})();

export const safeStorage = storage;