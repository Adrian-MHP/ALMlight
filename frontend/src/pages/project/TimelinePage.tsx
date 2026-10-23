import { useMemo, useRef, useState } from "react";
import {
  ActionIcon, Alert, Button, Card, Drawer, Group, Menu, Modal, SegmentedControl, Select, Stack, Switch, Text, Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconDots, IconFlag, IconLink, IconPlus, IconTarget, IconTimeline } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import { pk, useBaselines, useTimeline } from "@/api/hooks";
import type { TimelineRow } from "@/api/types";
import { ItemPicker } from "@/components/ItemPicker";
import { ItemPreview } from "@/components/ItemPreview";
import { PageHeader } from "@/components/PageHeader";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";

const DAY = 86400000;
const ROW = 34;
const ZOOM = { weeks: 26, months: 7, quarters: 2.6 } as const;
type Zoom = keyof typeof ZOOM;

const toDay = (s: string) => Math.round(new Date(`${s}T00:00:00Z`).getTime() / DAY);
const fromDay = (d: number) => new Date(d * DAY).toISOString().slice(0, 10);

interface Node extends TimelineRow { depth: number }

/** Order rows as a hierarchy: release → iterations/milestones → tasks; unplanned tasks last. */
function hierarchy(rows: TimelineRow[]): Node[] {
  const byParent = new Map<string | null, TimelineRow[]>();
  const keys = new Set(rows.map((r) => r.key));
  for (const r of rows) {
    const p = r.parent && keys.has(r.parent) ? r.parent : null;
    byParent.set(p, [...(byParent.get(p) ?? []), r]);
  }
  const rank = (r: TimelineRow) => (r.kind === "release" ? 0 : r.kind === "iteration" ? 1 : r.kind === "task" ? 2 : 3);
  const sortRows = (list: TimelineRow[]) => [...list].sort((a, b) =>
    (a.start_date ?? a.due_date ?? "9999").localeCompare(b.start_date ?? b.due_date ?? "9999") || rank(a) - rank(b) || a.key.localeCompare(b.key));
  const out: Node[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const r of sortRows(byParent.get(parent) ?? [])) {
      if (parent === null && r.kind === "task") continue;
      out.push({ ...r, depth });
      walk(r.key, depth + 1);
    }
  };
  walk(null, 0);
  const unplanned = sortRows((byParent.get(null) ?? []).filter((r) => r.kind === "task"));
  if (unplanned.length) out.push(...unplanned.map((r) => ({ ...r, depth: 0 })));
  return out;
}

/** Gantt timeline (Teamcenter Schedule Manager style): plans, tasks and milestones with dependencies. */
export function TimelinePage() {
  const { key, model, can } = useProjectCtx();
  const qc = useQueryClient();
  const baselines = useBaselines(key).data ?? [];
  const [baseline, setBaseline] = useState<string | null>(null);
  const { data } = useTimeline(key, baseline);
  const [zoom, setZoom] = useState<Zoom>("weeks");
  const [critical, setCritical] = useState(true);
  const [overrides, setOverrides] = useState<Record<string, { start: string | null; due: string | null }>>({});
  const [preview, setPreview] = useState<string | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const [depFor, setDepFor] = useState<string | null>(null);
  const editable = can("contributor");
  const scrolled = useRef<string | null>(null);
  // the order comes from the saved dates only: re-sorting while a bar is dragged would move its DOM node and end the drag
  const ordered = useMemo(() => hierarchy(data?.rows ?? []), [data]);
  const rows = useMemo(() => ordered.map((r) => overrides[r.key]
    ? { ...r, start_date: overrides[r.key].start, due_date: overrides[r.key].due } : r), [ordered, overrides]);
  if (!data) return null;
  if (!data.enabled) return <><PageHeader title="Timeline" /><Text c="dimmed">This project's information model has no release or task type.</Text></>;
  const px = ZOOM[zoom];
  const dated = rows.filter((r) => r.start_date || r.due_date);
  const today = toDay(data.today);
  const days = dated.flatMap((r) => [r.start_date, r.due_date, r.baseline?.start_date, r.baseline?.due_date].filter(Boolean).map((d) => toDay(d!)));
  const first = Math.min(today, ...days) - (zoom === "weeks" ? 7 : 21);
  const last = Math.max(today, ...days) + (zoom === "weeks" ? 14 : 45);
  const width = (last - first + 1) * px;
  const x = (d: number) => (d - first) * px;
  const index = new Map(rows.map((r, i) => [r.key, i]));

  async function save(row: TimelineRow, start: string | null, due: string | null) {
    setOverrides((o) => ({ ...o, [row.key]: { start, due } }));
    try {
      const fields: Record<string, string | null> = { due_date: due };
      if (row.kind !== "milestone") fields.start_date = start;
      await api.patch(`/projects/${key}/items/${row.key}`, { fields });
      notifications.show({ color: "teal", message: `${row.key}: ${row.kind === "milestone" ? due : `${start} → ${due}`}` });
    } catch (e) {
      notifications.show({ color: "red", title: `${row.key} not rescheduled`, message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      await qc.invalidateQueries({ queryKey: pk(key, "timeline") });
      setOverrides((o) => { const n = { ...o }; delete n[row.key]; return n; });
    }
  }
  const months: { d: number; label: string }[] = [];
  for (let d = first; d <= last; d++) {
    const date = new Date(d * DAY);
    if (date.getUTCDate() === 1 || d === first) months.push({ d, label: date.toLocaleDateString(undefined, { month: "short", year: "numeric", timeZone: "UTC" }) });
  }
  const weeks: { d: number; label: string }[] = [];
  if (zoom !== "quarters") {
    for (let d = first; d <= last; d++) {
      const date = new Date(d * DAY);
      if (date.getUTCDay() === 1) weeks.push({ d, label: zoom === "weeks" ? `W${isoWeek(date)} · ${date.getUTCDate()}.${date.getUTCMonth() + 1}.` : `${date.getUTCDate()}` });
    }
  }
  const criticalCount = rows.filter((r) => r.critical).length;
  return (
    <>
      <PageHeader title="Timeline" subtitle="Schedule of releases, iterations, milestones and tasks: dependencies, critical path, baseline comparison — drag bars to reschedule"
        actions={editable && data.task_type && (
          <Group gap="xs">
            <Button variant="default" leftSection={<IconFlag size={16} />} onClick={() => setCreating(data.release_type)} data-testid="new-plan">New plan / milestone</Button>
            <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(data.task_type!)} data-testid="new-task">New task</Button>
          </Group>
        )} />
      <Card withBorder mb="sm" padding="sm">
        <Group justify="space-between" wrap="wrap">
          <Group gap="md" wrap="wrap">
            <SegmentedControl size="xs" value={zoom} onChange={(v) => setZoom(v as Zoom)} data-testid="tl-zoom"
              data={[{ value: "weeks", label: "Weeks" }, { value: "months", label: "Months" }, { value: "quarters", label: "Quarters" }]} />
            <Switch size="sm" label={`Critical path${criticalCount ? ` (${criticalCount})` : ""}`} checked={critical} onChange={(e) => setCritical(e.currentTarget.checked)} data-testid="tl-critical" />
            <Select size="xs" w={260} placeholder="Compare with baseline…" clearable value={baseline} onChange={setBaseline} data-testid="tl-baseline"
              data={baselines.map((b) => ({ value: b.id, label: b.name }))} />
          </Group>
          <Group gap="md">
            <Legend swatch="tl-sw-task" label="task" />
            <Legend swatch="tl-sw-plan" label="release / iteration" />
            <Legend swatch="tl-sw-ms" label="milestone" />
            {critical && <Legend swatch="tl-sw-crit" label="critical" />}
            {baseline && <Legend swatch="tl-sw-base" label="baseline" />}
          </Group>
        </Group>
      </Card>
      {data.conflicts.length > 0 && (
        <Alert color="orange" icon={<IconAlertTriangle size={16} />} mb="sm" data-testid="tl-conflicts" title={`${data.conflicts.length} scheduling conflict(s)`}>
          {data.conflicts.map((c) => <Text key={`${c.item}-${c.depends_on}`} size="sm">{c.message}</Text>)}
        </Alert>
      )}
      <Card withBorder padding={0} className="gantt" data-testid="timeline">
        <div className="gantt-left">
          <div className="gantt-lhead" style={{ height: 44 }}>
            <span>Name</span><span>Start</span><span>Finish</span><span>%</span>
          </div>
          {rows.map((r) => (
            <div key={r.key} className={`gantt-lrow${r.critical && critical ? " is-critical" : ""}`} style={{ height: ROW }} data-testid={`tl-row-${r.key}`}>
              <span className="gantt-name" style={{ paddingLeft: 8 + r.depth * 16 }}>
                {r.kind === "milestone" ? <IconFlag size={13} /> : r.kind === "task" ? <IconTarget size={13} /> : <IconTimeline size={13} />}
                <Text component="span" size="xs" className="item-key clickable" onClick={() => setPreview(r.key)}>{r.key}</Text>
                <Text component="span" size="xs" truncate title={r.title}>{r.title}</Text>
              </span>
              <span className="mono">{r.kind === "milestone" ? "" : short(r.start_date)}</span>
              <span className="mono">{short(r.due_date)}</span>
              <span>
                {r.kind === "milestone" ? "" : `${Math.round(r.progress * 100)}`}
                {editable && data.dependency_link && (
                  <Menu position="bottom-end" withinPortal>
                    <Menu.Target><ActionIcon size="xs" variant="subtle" color="gray" aria-label={`Actions for ${r.key}`} data-testid={`tl-menu-${r.key}`}><IconDots size={12} /></ActionIcon></Menu.Target>
                    <Menu.Dropdown>
                      <Menu.Item leftSection={<IconLink size={14} />} onClick={() => setDepFor(r.key)} data-testid="tl-add-dep">Add predecessor…</Menu.Item>
                      <Menu.Item onClick={() => setPreview(r.key)}>Details</Menu.Item>
                    </Menu.Dropdown>
                  </Menu>
                )}
              </span>
            </div>
          ))}
          {rows.length === 0 && <Text size="sm" c="dimmed" p="md">No plans or tasks yet.</Text>}
        </div>
        <div className="gantt-right" ref={(el) => {
          if (el && scrolled.current !== zoom) { scrolled.current = zoom; el.scrollLeft = Math.max(0, x(today - (zoom === "weeks" ? 10 : 30))); }
        }}>
          <div style={{ width, position: "relative" }}>
            <div className="gantt-scale" style={{ height: 44 }}>
              {months.map((m) => <span key={`m${m.d}`} className="gantt-month" style={{ left: x(m.d) }}>{m.label}</span>)}
              {weeks.map((w) => <span key={`w${w.d}`} className="gantt-week" style={{ left: x(w.d) }}>{w.label}</span>)}
            </div>
            <div className="gantt-body" style={{ height: rows.length * ROW }}>
              {weeks.map((w) => <div key={`g${w.d}`} className="gantt-grid" style={{ left: x(w.d) }} />)}
              <div className="gantt-today" style={{ left: x(today) + px / 2 }} title={`Today ${data.today}`} data-testid="tl-today" />
              <Dependencies rows={rows} index={index} x={x} px={px} conflicts={new Set(data.conflicts.map((c) => `${c.item}>${c.depends_on}`))} critical={critical} />
              {rows.map((r, i) => (
                <Bar key={r.key} row={r} top={i * ROW} x={x} px={px} critical={critical} editable={editable && !r.frozen}
                  onSave={(s, d) => save(r, s, d)} onOpen={() => setPreview(r.key)}
                  onDrag={(s, d) => setOverrides((o) => ({ ...o, [r.key]: { start: s, due: d } }))} />
              ))}
            </div>
          </div>
        </div>
      </Card>
      <Drawer opened={!!preview} onClose={() => setPreview(null)} position="right" size="lg" withCloseButton={false} padding="xs">
        {preview && <ItemPreview projectKey={key} itemKey={preview} model={model} onClose={() => setPreview(null)} />}
      </Drawer>
      {creating && <ItemFormModal opened onClose={() => setCreating(null)} defaultType={creating} types={[creating]} navigateOnCreate={false}
        onSaved={() => qc.invalidateQueries({ queryKey: pk(key, "timeline") })} />}
      {depFor && <DependencyModal itemKey={depFor} types={[data.task_type, data.release_type].filter(Boolean) as string[]} linkType={data.dependency_link!}
        onClose={() => setDepFor(null)} />}
    </>
  );
}

function short(d: string | null): string {
  return d ? `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(2, 4)}` : "";
}

function isoWeek(d: Date): number {
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t.getTime() - y.getTime()) / DAY + 1) / 7);
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return <Group gap={4}><span className={`tl-sw ${swatch}`} /><Text size="xs" c="dimmed">{label}</Text></Group>;
}

function Bar({ row, top, x, px, critical, editable, onSave, onOpen, onDrag }: {
  row: Node; top: number; x: (d: number) => number; px: number; critical: boolean; editable: boolean;
  onSave: (start: string | null, due: string | null) => void; onOpen: () => void; onDrag: (start: string | null, due: string | null) => void;
}) {
  const drag = useRef<{ mode: "move" | "start" | "end"; x0: number; s: number; d: number; moved: boolean } | null>(null);
  if (!row.due_date && !row.start_date) return null;
  const s = toDay(row.start_date ?? row.due_date!), d = toDay(row.due_date ?? row.start_date!);
  const isCrit = critical && row.critical;
  const base = row.baseline && (row.baseline.start_date || row.baseline.due_date)
    ? { s: toDay(row.baseline.start_date ?? row.baseline.due_date!), d: toDay(row.baseline.due_date ?? row.baseline.start_date!) } : null;
  function down(e: React.PointerEvent, mode: "move" | "start" | "end") {
    if (!editable) return;
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { mode, x0: e.clientX, s, d, moved: false };
  }
  function move(e: React.PointerEvent) {
    const g = drag.current;
    if (!g) return;
    const delta = Math.round((e.clientX - g.x0) / px);
    if (delta === 0 && !g.moved) return;
    g.moved = true;
    let ns = g.s, nd = g.d;
    if (g.mode === "move") { ns += delta; nd += delta; } else if (g.mode === "start") ns = Math.min(g.s + delta, g.d); else nd = Math.max(g.d + delta, g.s);
    onDrag(row.kind === "milestone" ? null : fromDay(ns), fromDay(nd));
  }
  function up(e: React.PointerEvent) {
    const g = drag.current;
    drag.current = null;
    if (!g) return;
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
    if (!g.moved) { onOpen(); return; }
    const delta = Math.round((e.clientX - g.x0) / px);
    let ns = g.s, nd = g.d;
    if (g.mode === "move") { ns += delta; nd += delta; } else if (g.mode === "start") ns = Math.min(g.s + delta, g.d); else nd = Math.max(g.d + delta, g.s);
    if (ns === g.s && nd === g.d) { onDrag(row.start_date, row.due_date); return; }
    onSave(row.kind === "milestone" ? null : fromDay(ns), fromDay(nd));
  }
  const tip = `${row.key} ${row.title}\n${row.kind === "milestone" ? row.due_date : `${row.start_date} → ${row.due_date}`} · ${Math.round(row.progress * 100)} %${row.slack != null ? ` · slack ${row.slack} d` : ""}${row.baseline ? `\nbaseline ${row.baseline.start_date ?? ""} → ${row.baseline.due_date ?? ""}` : ""}`;
  if (row.kind === "milestone") {
    return (
      <>
        {base && <div className="tl-base-ms" style={{ left: x(base.d) + px / 2 - 5, top: top + 22 }} title={`Baseline ${row.baseline?.due_date}`} />}
        <Tooltip label={<span style={{ whiteSpace: "pre-line" }}>{tip}</span>} withinPortal>
          <div className={`tl-ms${isCrit ? " is-critical" : ""}${editable ? " is-editable" : ""}`} style={{ left: x(d) + px / 2 - 8, top: top + 9 }}
            onPointerDown={(e) => down(e, "move")} onPointerMove={move} onPointerUp={up} data-testid={`tl-bar-${row.key}`} />
        </Tooltip>
        <Text className="tl-label" size="xs" style={{ left: x(d) + px / 2 + 12, top: top + 9 }}>{row.title}</Text>
      </>
    );
  }
  const left = x(s), w = Math.max(px, (d - s + 1) * px);
  const plan = row.kind !== "task";
  return (
    <>
      {base && <div className="tl-base" style={{ left: x(base.s), width: Math.max(px, (base.d - base.s + 1) * px), top: top + (plan ? 22 : 26) }}
        title={`Baseline ${row.baseline?.start_date} → ${row.baseline?.due_date}`} data-testid={`tl-base-${row.key}`} />}
      <Tooltip label={<span style={{ whiteSpace: "pre-line" }}>{tip}</span>} withinPortal openDelay={300}>
        <div className={`${plan ? "tl-plan" : "tl-task"} tl-st-${row.state_category ?? "open"}${isCrit ? " is-critical" : ""}${editable ? " is-editable" : ""}`}
          style={{ left, width: w, top: top + (plan ? 10 : 7) }} data-testid={`tl-bar-${row.key}`}
          onPointerDown={(e) => down(e, "move")} onPointerMove={move} onPointerUp={up}>
          <div className="tl-progress" style={{ width: `${Math.round(row.progress * 100)}%` }} />
          {editable && <span className="tl-handle tl-h-start" onPointerDown={(e) => down(e, "start")} onPointerMove={move} onPointerUp={up} />}
          {editable && <span className="tl-handle tl-h-end" onPointerDown={(e) => down(e, "end")} onPointerMove={move} onPointerUp={up} data-testid={`tl-end-${row.key}`} />}
        </div>
      </Tooltip>
      {!plan && <Text className="tl-label" size="xs" style={{ left: left + w + 6, top: top + 9 }}>{row.title}</Text>}
    </>
  );
}

function Dependencies({ rows, index, x, px, conflicts, critical }: {
  rows: Node[]; index: Map<string, number>; x: (d: number) => number; px: number; conflicts: Set<string>; critical: boolean;
}) {
  const paths: { d: string; cls: string; id: string }[] = [];
  for (const r of rows) {
    const ti = index.get(r.key);
    if (ti === undefined || !(r.start_date || r.due_date)) continue;
    for (const p of r.depends_on) {
      const pi = index.get(p);
      const pr = pi !== undefined ? rows[pi] : undefined;
      if (pi === undefined || !pr || !(pr.due_date || pr.start_date)) continue;
      const x1 = x(toDay(pr.due_date ?? pr.start_date!)) + (pr.kind === "milestone" ? px / 2 + 8 : px);
      const y1 = pi * ROW + ROW / 2;
      const x2 = x(toDay(r.kind === "milestone" ? r.due_date! : (r.start_date ?? r.due_date!))) + (r.kind === "milestone" ? px / 2 - 9 : 0);
      const y2 = ti * ROW + ROW / 2;
      const mid = Math.max(x1 + 8, Math.min(x2 - 8, x1 + 14));
      const d = x2 >= x1 + 10 ? `M${x1},${y1} H${mid} V${y2} H${x2 - 2}` : `M${x1},${y1} h8 V${(y1 + y2) / 2} H${x2 - 12} V${y2} H${x2 - 2}`;
      const conflict = conflicts.has(`${r.key}>${p}`);
      const crit = critical && r.critical && pr.critical;
      paths.push({ d, cls: conflict ? "tl-dep is-conflict" : crit ? "tl-dep is-critical" : "tl-dep", id: `${p}>${r.key}` });
    }
  }
  const h = rows.length * ROW;
  return (
    <svg className="tl-deps" width="100%" height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }} data-testid="tl-deps">
      <defs>
        <marker id="tl-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--mantine-color-gray-6)" /></marker>
        <marker id="tl-arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--mantine-color-red-6)" /></marker>
      </defs>
      {paths.map((p) => <path key={p.id} d={p.d} className={p.cls} markerEnd={p.cls.includes("is-") ? "url(#tl-arrow-red)" : "url(#tl-arrow)"} data-testid={`tl-dep-${p.id}`} />)}
    </svg>
  );
}

function DependencyModal({ itemKey, types, linkType, onClose }: { itemKey: string; types: string[]; linkType: string; onClose: () => void }) {
  const { key } = useProjectCtx();
  const qc = useQueryClient();
  const [pred, setPred] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function add() {
    setBusy(true);
    try {
      await api.post(`/projects/${key}/links`, { type: linkType, source: itemKey, target: pred });
      notifications.show({ color: "teal", message: `${itemKey} now starts after ${pred} finishes` });
      qc.invalidateQueries({ queryKey: pk(key) });
      onClose();
    } catch (e) {
      notifications.show({ color: "red", message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal opened onClose={onClose} title={`Predecessor of ${itemKey}`}>
      <Stack>
        <Text size="sm" c="dimmed">Finish-to-start: {itemKey} starts when the predecessor is finished.</Text>
        <ItemPicker label="Predecessor" types={types} exclude={[itemKey]} value={pred} onChange={setPred} testId="tl-dep-picker" />
        <Group justify="flex-end"><Button onClick={add} disabled={!pred} loading={busy} data-testid="tl-dep-save">Add dependency</Button></Group>
      </Stack>
    </Modal>
  );
}

