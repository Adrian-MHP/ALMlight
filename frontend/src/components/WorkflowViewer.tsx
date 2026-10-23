import { useMemo } from "react";
import { Group, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { pk, useTransitions } from "@/api/hooks";
import type { Item } from "@/api/types";
import { stateColor, type Model } from "@/lib/model";
import { tm, tx } from "@/lib/i18n";

interface WfEvent { from: string | null; to: string; transition: string; at: string }

const W = 104, H = 34, GX = 100, GY = 26, PAD = 16;

function cssColor(c: string): string {
  const [name, shade] = c.split(".");
  return `var(--mantine-color-${name}-${shade ?? 6})`;
}

/** State diagram of the item's workflow: current state, the path taken so far and the transitions possible now. */
export function WorkflowViewer({ projectKey, item, model, compact = false }: { projectKey: string; item: Item; model: Model; compact?: boolean }) {
  const wf = model.workflow(item.type_key);
  const events = useQuery<WfEvent[]>({
    queryKey: pk(projectKey, "item", item.key, "workflow-events"),
    queryFn: () => api.get(`/projects/${projectKey}/items/${item.key}/workflow-events`),
  }).data ?? [];
  const allowed = new Set((useTransitions(projectKey, item.key).data ?? []).filter((t) => t.allowed).map((t) => t.key));
  const layout = useMemo(() => {
    if (!wf) return null;
    const level = new Map<string, number>();
    const initial = wf.states.find((s) => s.initial) ?? wf.states[0];
    const queue = [initial.key];
    level.set(initial.key, 0);
    while (queue.length) {
      const s = queue.shift()!;
      for (const t of wf.transitions) {
        if (t.from.includes(s) && !level.has(t.to)) { level.set(t.to, level.get(s)! + 1); queue.push(t.to); }
      }
    }
    const maxLevel = Math.max(0, ...level.values());
    for (const s of wf.states) if (!level.has(s.key)) level.set(s.key, maxLevel + 1);
    // boxes and gaps grow with the labels (German labels are longer)
    const w = Math.max(W, ...wf.states.map((s) => Math.ceil(s.label.length * 7.2 + 20)));
    const rows = new Map<number, number>();
    const pos = new Map<string, { x: number; y: number }>();
    const edges = new Map<string, { from: string; to: string; labels: string[]; keys: string[] }>();
    for (const t of wf.transitions) {
      for (const f of t.from) {
        const id = `${f}>${t.to}`;
        const e = edges.get(id) ?? { from: f, to: t.to, labels: [], keys: [] };
        e.labels.push(t.label); e.keys.push(t.key);
        edges.set(id, e);
      }
    }
    const forwardLabels = [...edges.values()].filter((e) => (level.get(e.to) ?? 0) > (level.get(e.from) ?? 0))
      .map((e) => e.labels.join(" / ").length);
    const gx = compact ? GX : Math.max(GX, ...forwardLabels.map((n) => Math.ceil(n * 5.8 + 28)));
    for (const s of wf.states) {
      const l = level.get(s.key)!;
      const r = rows.get(l) ?? 0;
      rows.set(l, r + 1);
      pos.set(s.key, { x: PAD + l * (w + gx), y: PAD + r * (H + GY) });
    }
    const width = PAD * 2 + (Math.max(...level.values()) + 1) * (w + gx) - gx;
    const height = PAD * 2 + Math.max(...rows.values()) * (H + GY) - GY + 40;
    return { pos, edges: [...edges.values()], width, height, level, w, gx };
  }, [wf, compact]);
  if (!wf || !layout) return null;
  const visited = new Set(events.flatMap((e) => [e.to, e.from].filter(Boolean) as string[]));
  const taken = new Set(events.map((e) => `${e.from}>${e.to}`));
  return (
    <div data-testid="workflow-viewer">
      <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${layout.width} ${layout.height}`} width={layout.width} height={layout.height} style={{ display: "block", maxWidth: "none" }}
        role="img" aria-label={tx("Workflow {label}, current state {label1}", { label: wf.label, label1: tm(item.lifecycle.label) ?? item.lifecycle.state })}>
        <defs>
          {["muted", "taken", "next"].map((k) => (
            <marker key={k} id={`wf-arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={k === "next" ? "var(--mantine-primary-color-filled)" : k === "taken" ? "var(--mantine-color-dark-3)" : "var(--mantine-color-gray-5)"} />
            </marker>
          ))}
        </defs>
        {layout.edges.map((e, i) => {
          const a = layout.pos.get(e.from)!, b = layout.pos.get(e.to)!;
          const forward = (layout.level.get(e.to) ?? 0) > (layout.level.get(e.from) ?? 0);
          const isNext = e.from === item.lifecycle.state && e.keys.some((k) => allowed.has(k));
          const isTaken = taken.has(`${e.from}>${e.to}`);
          const stroke = isNext ? "var(--mantine-primary-color-filled)" : isTaken ? "var(--mantine-color-dark-3)" : "var(--mantine-color-gray-5)";
          let d: string, lx: number, ly: number;
          if (forward) {
            const x1 = a.x + layout.w, y1 = a.y + H / 2, x2 = b.x - 2, y2 = b.y + H / 2;
            d = `M${x1},${y1} C${x1 + layout.gx / 2},${y1} ${x2 - layout.gx / 2},${y2} ${x2},${y2}`;
            lx = (x1 + x2) / 2; ly = (y1 + y2) / 2 - 4;
          } else {
            const x1 = a.x + layout.w / 2 + 10, y1 = a.y + H, x2 = b.x + layout.w / 2 - 10, y2 = b.y + H + 2;
            const dip = Math.max(y1, y2) + 26 + (i % 2) * 8;
            d = `M${x1},${y1} C${x1},${dip} ${x2},${dip} ${x2},${y2}`;
            lx = (x1 + x2) / 2; ly = dip - 4;
          }
          return (
            <g key={`${e.from}-${e.to}`} data-testid={isNext ? `wf-next-${e.to}` : undefined}>
              <path d={d} fill="none" stroke={stroke} strokeWidth={isNext ? 2.2 : isTaken ? 1.6 : 1.1}
                strokeDasharray={isNext || isTaken ? undefined : "4 3"} markerEnd={`url(#wf-arrow-${isNext ? "next" : isTaken ? "taken" : "muted"})`} />
              {!compact && (
                <text x={lx} y={ly} textAnchor="middle" fontSize="10" fill={isNext ? "var(--mantine-primary-color-filled)" : "var(--mantine-color-dimmed)"}
                  style={{ paintOrder: "stroke", stroke: "var(--mantine-color-body)", strokeWidth: 3 }}>{e.labels.join(" / ")}</text>
              )}
            </g>
          );
        })}
        {wf.states.map((s) => {
          const p = layout.pos.get(s.key)!;
          const current = s.key === item.lifecycle.state;
          const color = cssColor(stateColor(s.color, s.category));
          return (
            <g key={s.key} data-testid={`wf-state-${s.key}`} data-current={current ? "true" : undefined}>
              <rect x={p.x} y={p.y} width={layout.w} height={H} rx={8} fill={current ? color : "var(--mantine-color-body)"}
                stroke={current || visited.has(s.key) ? color : "var(--mantine-color-default-border)"} strokeWidth={current ? 2.5 : visited.has(s.key) ? 2 : 1} />
              <text x={p.x + layout.w / 2} y={p.y + H / 2 + 4} textAnchor="middle" fontSize="12" fontWeight={current ? 700 : 500}
                fill={current ? "#fff" : "var(--mantine-color-text)"}>{s.label}</text>
            </g>
          );
        })}
      </svg>
      </div>
      {!compact && (
        <Group gap="md" mt={4}>
          <Legend color="var(--mantine-primary-color-filled)" label={tx("possible for you now")} />
          <Legend color="var(--mantine-color-dark-3)" label={tx("path taken")} />
          <Legend color="var(--mantine-color-gray-5)" dashed label={tx("other transitions")} />
        </Group>
      )}
    </div>
  );
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <Group gap={4}>
      <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke={color} strokeWidth="2" strokeDasharray={dashed ? "4 3" : undefined} /></svg>
      <Text size="xs" c="dimmed">{label}</Text>
    </Group>
  );
}
