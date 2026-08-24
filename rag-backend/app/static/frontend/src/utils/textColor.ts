/**
 * Контрастный цвет текста (white / dark) для заданного цвета фона.
 * Используется для бейджей тегов: обеспечивает читаемость на любом фоне.
 */

function clamp(n: number, min = 0, max = 255): number {
  return Math.min(Math.max(n, min), max);
}

function parseHex(hex: string): { r: number; g: number; b: number } | null {
  const h = hex.trim().replace('#', '');
  if (h.length === 3) {
    const r = parseInt(h[0]! + h[0]!, 16);
    const g = parseInt(h[1]! + h[1]!, 16);
    const b = parseInt(h[2]! + h[2]!, 16);
    if ([r, g, b].some(Number.isNaN)) return null;
    return { r, g, b };
  }
  if (h.length === 6) {
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    if ([r, g, b].some(Number.isNaN)) return null;
    return { r, g, b };
  }
  return null;
}

export function contrastTextColor(bg?: string | null): 'white' | '#1f2937' {
  if (!bg) return 'white';
  const rgb = parseHex(bg);
  if (!rgb) return 'white';
  // Relative luminance per WCAG (sRGB linearised).
  const linear = (c: number): number => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const L = 0.2126 * linear(clamp(rgb.r)) + 0.7152 * linear(clamp(rgb.g)) + 0.0722 * linear(clamp(rgb.b));
  return L > 0.55 ? '#1f2937' : 'white';
}