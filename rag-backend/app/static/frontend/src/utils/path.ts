export function basename(path?: string | null): string {
  if (!path) return '';
  const norm = path.replace(/\\/g, '/');
  const idx = norm.lastIndexOf('/');
  const last = idx >= 0 ? norm.slice(idx + 1) : norm;
  return last || path;
}

export function stripExt(name: string): string {
  const idx = name.lastIndexOf('.');
  return idx > 0 ? name.slice(0, idx) : name;
}