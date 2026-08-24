/**
 * Базовый HTTP-клиент. Все доменные mixin'ы используют эти методы.
 *
 * Миграция с `js/api/*` (ванильный JS с mixin'ами) → TS-классы.
 * Поведение API не меняется — только типы и сигнатуры.
 */

export class HttpError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, fallbackMessage: string) {
    const message = formatDetail(detail, fallbackMessage);
    super(message);
    this.name = 'HttpError';
    this.status = status;
    this.detail = detail;
  }

  isCode(code: string): boolean {
    if (typeof this.detail === 'string') {
      return this.detail === code;
    }
    if (this.detail && typeof this.detail === 'object' && 'code' in this.detail) {
      return (this.detail as { code?: unknown }).code === code;
    }
    return false;
  }
}

function formatDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((e) => {
        if (!e || typeof e !== 'object') return '';
        const obj = e as { loc?: unknown[]; msg?: string };
        const loc = Array.isArray(obj.loc)
          ? obj.loc.filter((p) => p !== 'body').join('.')
          : '';
        return loc ? `${loc}: ${obj.msg ?? ''}` : (obj.msg ?? '');
      })
      .filter(Boolean);
    if (parts.length) return parts.join('; ');
  }
  return fallback;
}

async function readJsonSafe<T = unknown>(response: Response): Promise<T | null> {
  try {
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

function extractDetail(body: unknown): unknown {
  if (body && typeof body === 'object' && 'detail' in body) {
    return (body as { detail: unknown }).detail;
  }
  return body;
}

export class HttpClient {
  baseUrl = '';

  async get<T>(path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`);
    if (!response.ok) {
      const body = await readJsonSafe(response);
      const detail = extractDetail(body);
      throw new HttpError(response.status, detail, response.statusText);
    }
    return (await response.json()) as T;
  }

  async post<T>(path: string, body?: unknown, options: { raw?: boolean } = {}): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return this.handleResponse<T>(response, options);
  }

  async put<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return this.handleResponse<T>(response);
  }

  async patch<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return this.handleResponse<T>(response);
  }

  async delete<T = void>(path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, { method: 'DELETE' });
    if (!response.ok && response.status !== 204) {
      const body = await readJsonSafe(response);
      const detail = extractDetail(body);
      throw new HttpError(response.status, detail, response.statusText);
    }
    if (response.status === 204) return undefined as T;
    if (response.headers.get('content-length') === '0') return undefined as T;
    return (await response.json()) as T;
  }

  private async handleResponse<T>(response: Response, options: { raw?: boolean } = {}): Promise<T> {
    if (!response.ok) {
      const body = await readJsonSafe(response);
      const detail = extractDetail(body);
      throw new HttpError(response.status, detail, response.statusText);
    }
    if (options.raw) return response as unknown as T;
    const ct = response.headers.get('content-type') ?? '';
    if (ct.includes('text/event-stream')) {
      return response.body as unknown as T;
    }
    return (await response.json()) as T;
  }
}