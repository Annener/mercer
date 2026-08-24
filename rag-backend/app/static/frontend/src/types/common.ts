export type Theme = 'light' | 'dark';

export type Result<T, E = Error> =
  | { ok: true; value: T }
  | { ok: false; error: E };

export type Nullable<T> = T | null | undefined;

export type ID = string;

export interface Paginated<T> {
  items: T[];
  total?: number;
  hasMore?: boolean;
}

export type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K];
};