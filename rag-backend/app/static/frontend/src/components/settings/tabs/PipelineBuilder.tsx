import { useRef, useState, type RefObject } from 'react';
import { Button, Card, Field, Input, Select, SelectWrapper } from '@/components/ui';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { Pipeline, PipelineStep } from '@/api/types';

interface PipelineBuilderProps {
  pipeline: Pipeline;
  onClose: () => void;
}

export function PipelineBuilder({ pipeline, onClose }: PipelineBuilderProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(pipeline.name);
  const [steps, setSteps] = useState<PipelineStep[]>(pipeline.steps ?? []);
  const [finalComposition, setFinalComposition] = useState(pipeline.final_composition ?? 'concatenate');
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const updateMutation = useMutation({
    mutationFn: () =>
      api.updatePipeline(pipeline.pipeline_id, {
        name,
        steps,
        final_composition: finalComposition,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['pipelines'] });
    },
  });

  const addStep = (type: 'retrieval' | 'validation') => {
    const id = `step_${Date.now()}`;
    setSteps((prev) => [
      ...prev,
      { id, name: type === 'retrieval' ? 'Retrieval' : 'Validation', type, depends_on: [], params: {} },
    ]);
    setSelectedStepId(id);
  };

  const updateStep = (id: string, patch: Partial<PipelineStep>) => {
    setSteps((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  };

  const removeStep = (id: string) => {
    setSteps((prev) =>
      prev
        .filter((s) => s.id !== id)
        .map((s) => ({ ...s, depends_on: s.depends_on?.filter((d) => d !== id) ?? [] })),
    );
    if (selectedStepId === id) setSelectedStepId(null);
  };

  const selected = steps.find((s) => s.id === selectedStepId) ?? null;

  return (
    <Card
      title={`Pipeline: ${pipeline.pipeline_id}`}
      actions={
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            ← Назад
          </Button>
          <Button size="sm" onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>
            Сохранить
          </Button>
        </div>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <div>
          <Field label="Название:">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>

          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={() => addStep('retrieval')}>
              + Retrieval
            </Button>
            <Button size="sm" onClick={() => addStep('validation')}>
              + Validation
            </Button>
          </div>

          <div className="mt-3 rounded border border-border bg-surface-2 p-2">
            {steps.length === 0 ? (
              <p className="py-8 text-center text-sm text-text-muted">
                Добавьте шаги пайплайна
              </p>
            ) : (
              <DagGraph
                steps={steps}
                selectedStepId={selectedStepId}
                onSelect={setSelectedStepId}
                svgRef={svgRef}
              />
            )}
          </div>

          <Field label="Final composition:" className="mt-3">
            <SelectWrapper>
              <Select
                value={finalComposition}
                onChange={(e) => setFinalComposition(e.target.value)}
                options={[
                  { value: 'concatenate', label: 'Concatenate' },
                  { value: 'merge', label: 'Merge' },
                  { value: 'last', label: 'Last wins' },
                ]}
              />
            </SelectWrapper>
          </Field>
        </div>

        <aside className="rounded border border-border p-3">
          {selected ? (
            <StepInspector
              step={selected}
              allSteps={steps}
              onChange={(patch) => updateStep(selected.id!, patch)}
              onRemove={() => removeStep(selected.id!)}
            />
          ) : (
            <p className="text-sm text-text-muted">
              Выберите шаг на графе для редактирования
            </p>
          )}
        </aside>
      </div>
    </Card>
  );
}

interface DagGraphProps {
  steps: PipelineStep[];
  selectedStepId: string | null;
  onSelect: (id: string) => void;
  svgRef: RefObject<SVGSVGElement | null>;
}

function DagGraph({ steps, selectedStepId, onSelect }: DagGraphProps) {
  const positions = computeLayout(steps);

  return (
    <svg
      width="100%"
      height={Math.max(200, steps.length * 80 + 40)}
      viewBox={`0 0 600 ${Math.max(200, steps.length * 80 + 40)}`}
      className="overflow-visible"
    >
      <defs>
        <marker
          id="arrowhead"
          markerWidth="10"
          markerHeight="7"
          refX="9"
          refY="3.5"
          orient="auto"
        >
          <polygon points="0 0, 10 3.5, 0 7" fill="currentColor" />
        </marker>
      </defs>

      {/* edges */}
      <g className="text-text-muted">
        {steps.flatMap((step) =>
          (step.depends_on ?? []).map((depId) => {
            const from = positions.get(depId);
            const to = positions.get(step.id!);
            if (!from || !to) return null;
            const x1 = from.x + 100;
            const y1 = from.y + 30;
            const x2 = to.x;
            const y2 = to.y + 30;
            const midY = (y1 + y2) / 2;
            return (
              <path
                key={`${depId}-${step.id}`}
                d={`M ${x1} ${y1} C ${x1 + 50} ${midY}, ${x2 - 50} ${midY}, ${x2} ${y2}`}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                markerEnd="url(#arrowhead)"
              />
            );
          }),
        )}
      </g>

      {/* nodes */}
      {steps.map((step) => {
        const pos = positions.get(step.id!);
        if (!pos) return null;
        const isSelected = step.id === selectedStepId;
        const isValidation = step.type === 'validation';
        return (
          <g
            key={step.id}
            transform={`translate(${pos.x}, ${pos.y})`}
            onClick={() => onSelect(step.id!)}
            style={{ cursor: 'pointer' }}
          >
            <rect
              width="100"
              height="60"
              rx="6"
              fill={isSelected ? 'var(--color-primary)' : 'var(--color-surface)'}
              stroke={isValidation ? 'var(--color-warning)' : 'var(--color-primary)'}
              strokeWidth="2"
            />
            <text
              x="50"
              y="25"
              textAnchor="middle"
              fill={isSelected ? 'white' : 'var(--color-text)'}
              fontSize="12"
              fontWeight="600"
            >
              {step.type}
            </text>
            <text
              x="50"
              y="45"
              textAnchor="middle"
              fill={isSelected ? 'white' : 'var(--color-text-muted)'}
              fontSize="11"
            >
              {step.name?.slice(0, 14)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function computeLayout(steps: PipelineStep[]): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  const byLevel: number[] = [];
  const levelOf = new Map<string, number>();

  // Topological level assignment
  for (const step of steps) {
    const visit = (id: string, seen: Set<string>): number => {
      if (levelOf.has(id)) return levelOf.get(id)!;
      if (seen.has(id)) return 0;
      seen.add(id);
      const s = steps.find((x) => x.id === id);
      if (!s || !s.depends_on?.length) {
        levelOf.set(id, 0);
        return 0;
      }
      const lvl = 1 + Math.max(...s.depends_on.map((d) => visit(d, seen)));
      levelOf.set(id, lvl);
      return lvl;
    };
    visit(step.id!, new Set());
  }

  for (const step of steps) {
    const lvl = levelOf.get(step.id!) ?? 0;
    byLevel[lvl] = (byLevel[lvl] ?? 0) + 1;
  }

  const countAtLevel = new Array(byLevel.length).fill(0);
  for (const step of steps) {
    const lvl = levelOf.get(step.id!) ?? 0;
    const idx = countAtLevel[lvl]!;
    countAtLevel[lvl] = idx + 1;
    pos.set(step.id!, {
      x: 50 + lvl * 180,
      y: 30 + idx * 80,
    });
  }
  return pos;
}

function StepInspector({
  step,
  allSteps,
  onChange,
  onRemove,
}: {
  step: PipelineStep;
  allSteps: PipelineStep[];
  onChange: (patch: Partial<PipelineStep>) => void;
  onRemove: () => void;
}) {
  const deps = step.depends_on ?? [];
  const otherSteps = allSteps.filter((s) => s.id !== step.id);

  const toggleDep = (id: string) => {
    const next = deps.includes(id) ? deps.filter((d) => d !== id) : [...deps, id];
    onChange({ depends_on: next });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold">{step.type}</h4>
        <Button size="sm" variant="danger" onClick={onRemove}>
          Удалить
        </Button>
      </div>

      <Field label="Название:">
        <Input value={step.name ?? ''} onChange={(e) => onChange({ name: e.target.value })} />
      </Field>

      <Field label="Зависит от:">
        <div className="space-y-1 rounded border border-border p-2">
          {otherSteps.length === 0 ? (
            <p className="text-xs text-text-muted">Нет других шагов</p>
          ) : (
            otherSteps.map((s) => (
              <label key={s.id} className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={deps.includes(s.id!)}
                  onChange={() => toggleDep(s.id!)}
                />
                <span>
                  {s.name} ({s.type})
                </span>
              </label>
            ))
          )}
        </div>
      </Field>
    </div>
  );
}