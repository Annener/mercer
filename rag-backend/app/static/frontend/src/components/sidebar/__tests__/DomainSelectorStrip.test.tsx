import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DomainSelectorStrip } from '../DomainSelectorStrip';
import type { Domain } from '@/api/types';

function makeDomain(id: string, display_name?: string): Domain {
  return {
    domain_id: id,
    display_name,
    is_system: false,
    enabled: true,
  };
}

const D_DND = makeDomain('dnd', 'D&D');
const D_WORK = makeDomain('work', 'Работа');
const D_DEMO = makeDomain('demo', 'Демо');

describe('DomainSelectorStrip — сетка по числу доменов', () => {
  beforeEach(() => vi.clearAllMocks());

  it('1 домен → 1 колонка', () => {
    render(
      <DomainSelectorStrip
        domains={[D_DND]}
        currentDomainId="dnd"
        onSelect={vi.fn()}
      />,
    );
    const grid = screen.getByRole('radiogroup');
    expect(grid.style.gridTemplateColumns).toBe('repeat(1, minmax(0, 1fr))');
  });

  it('2 домена → 2 колонки (делят строку пополам)', () => {
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK]}
        currentDomainId={null}
        onSelect={vi.fn()}
      />,
    );
    const grid = screen.getByRole('radiogroup');
    expect(grid.style.gridTemplateColumns).toBe('repeat(2, minmax(0, 1fr))');
  });

  it('3 домена → 3 колонки', () => {
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK, D_DEMO]}
        currentDomainId={null}
        onSelect={vi.fn()}
      />,
    );
    const grid = screen.getByRole('radiogroup');
    expect(grid.style.gridTemplateColumns).toBe('repeat(3, minmax(0, 1fr))');
  });

  it('4 домена → 2 колонки (2 строки по 2)', () => {
    const four = [...[D_DND, D_WORK, D_DEMO], makeDomain('extra', 'Доп')];
    render(
      <DomainSelectorStrip domains={four} currentDomainId={null} onSelect={vi.fn()} />,
    );
    expect(screen.getByRole('radiogroup').style.gridTemplateColumns).toBe(
      'repeat(2, minmax(0, 1fr))',
    );
  });

  it('5 доменов → 3 колонки (последняя строка неполная)', () => {
    const five = [...[D_DND, D_WORK, D_DEMO], makeDomain('a', 'A'), makeDomain('b', 'B')];
    render(
      <DomainSelectorStrip domains={five} currentDomainId={null} onSelect={vi.fn()} />,
    );
    expect(screen.getByRole('radiogroup').style.gridTemplateColumns).toBe(
      'repeat(3, minmax(0, 1fr))',
    );
  });

  it('6 доменов → 3 колонки (2 строки по 3)', () => {
    const six = [
      ...[D_DND, D_WORK, D_DEMO],
      makeDomain('a', 'A'),
      makeDomain('b', 'B'),
      makeDomain('c', 'C'),
    ];
    render(
      <DomainSelectorStrip domains={six} currentDomainId={null} onSelect={vi.fn()} />,
    );
    expect(screen.getByRole('radiogroup').style.gridTemplateColumns).toBe(
      'repeat(3, minmax(0, 1fr))',
    );
  });

  it('9 доменов → 3 колонки (3 строки по 3)', () => {
    const nine = Array.from({ length: 9 }, (_, i) =>
      makeDomain(`d${i}`, `D${i}`),
    );
    render(
      <DomainSelectorStrip domains={nine} currentDomainId={null} onSelect={vi.fn()} />,
    );
    expect(screen.getByRole('radiogroup').style.gridTemplateColumns).toBe(
      'repeat(3, minmax(0, 1fr))',
    );
  });
});

describe('DomainSelectorStrip — подсветка активного', () => {
  beforeEach(() => vi.clearAllMocks());

  it('активный домен получает primary-фон, border и aria-checked=true', () => {
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK]}
        currentDomainId="dnd"
        onSelect={vi.fn()}
      />,
    );
    const active = screen.getByTestId('domain-item-dnd');
    expect(active).toHaveClass('border-primary');
    expect(active).toHaveClass('bg-primary/15');
    expect(active).toHaveClass('text-primary');
    expect(active).toHaveAttribute('aria-checked', 'true');
  });

  it('неактивный домен имеет aria-checked=false и не подсвечен', () => {
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK]}
        currentDomainId="dnd"
        onSelect={vi.fn()}
      />,
    );
    const inactive = screen.getByTestId('domain-item-work');
    expect(inactive).toHaveAttribute('aria-checked', 'false');
    expect(inactive).not.toHaveClass('bg-primary/15');
    expect(inactive).toHaveClass('text-text-muted');
  });

  it('без currentDomainId ни один домен не подсвечен', () => {
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK]}
        currentDomainId={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByTestId('domain-item-dnd')).not.toHaveClass('bg-primary/15');
    expect(screen.getByTestId('domain-item-work')).not.toHaveClass('bg-primary/15');
  });
});

describe('DomainSelectorStrip — адаптивный шрифт', () => {
  beforeEach(() => vi.clearAllMocks());

  it('1 колонка → text-sm', () => {
    render(
      <DomainSelectorStrip
        domains={[D_DND]}
        currentDomainId="dnd"
        onSelect={vi.fn()}
      />,
    );
    const btn = screen.getByTestId('domain-item-dnd');
    expect(btn.className).toMatch(/text-sm/);
  });

  it('2 колонки → text-xs', () => {
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK]}
        currentDomainId={null}
        onSelect={vi.fn()}
      />,
    );
    const btn = screen.getByTestId('domain-item-dnd');
    expect(btn.className).toMatch(/text-xs/);
  });

  it('3 колонки + короткое имя → text-[11px]', () => {
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK, D_DEMO]}
        currentDomainId={null}
        onSelect={vi.fn()}
      />,
    );
    const btn = screen.getByTestId('domain-item-demo');
    expect(btn.className).toMatch(/text-\[11px\]/);
    expect(btn.className).not.toMatch(/text-\[10px\]/);
  });

  it('3 колонки + длинное имя (>8 символов) → text-[10px]', () => {
    const longName = makeDomain('long', 'Длинное имя');
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK, longName]}
        currentDomainId={null}
        onSelect={vi.fn()}
      />,
    );
    const btn = screen.getByTestId('domain-item-long');
    expect(btn.className).toMatch(/text-\[10px\]/);
  });
});

describe('DomainSelectorStrip — взаимодействие', () => {
  beforeEach(() => vi.clearAllMocks());

  it('клик по неактивному вызывает onSelect с правильным id', () => {
    const onSelect = vi.fn();
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK]}
        currentDomainId="dnd"
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByTestId('domain-item-work'));
    expect(onSelect).toHaveBeenCalledWith('work');
  });

  it('клик по активному тоже вызывает onSelect (idempotent)', () => {
    const onSelect = vi.fn();
    render(
      <DomainSelectorStrip
        domains={[D_DND, D_WORK]}
        currentDomainId="dnd"
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByTestId('domain-item-dnd'));
    expect(onSelect).toHaveBeenCalledWith('dnd');
  });
});

describe('DomainSelectorStrip — состояния', () => {
  beforeEach(() => vi.clearAllMocks());

  it('рендерит «Нет доменов» при пустом списке', () => {
    render(
      <DomainSelectorStrip
        domains={[]}
        currentDomainId={null}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(/Нет доменов/i)).toBeInTheDocument();
  });

  it('показывает 3 skeleton-плейсхолдера при loading=true', () => {
    render(
      <DomainSelectorStrip
        domains={[]}
        currentDomainId={null}
        onSelect={vi.fn()}
        loading
      />,
    );
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument();
    const skeletons = document.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBe(3);
  });

  it('fallback на UPPERCASE для неизвестных domain_id без display_name', () => {
    render(
      <DomainSelectorStrip
        domains={[makeDomain('mystery')]}
        currentDomainId="mystery"
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText('MYSTERY')).toBeInTheDocument();
  });

  it('применяет SPECIAL_NAMES для dnd без display_name', () => {
    render(
      <DomainSelectorStrip
        domains={[makeDomain('dnd')]}
        currentDomainId="dnd"
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText('D&D')).toBeInTheDocument();
  });

  it('применяет SPECIAL_NAMES для work без display_name', () => {
    render(
      <DomainSelectorStrip
        domains={[makeDomain('work')]}
        currentDomainId="work"
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText('Работа')).toBeInTheDocument();
  });
});
