import { useMemo, useRef, useState } from "react";
import {
  ActionIcon, Alert, Button, Card, Drawer, Group, Menu, Modal, NumberInput, SegmentedControl, Select, Stack, Switch, Table, Text,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertTriangle, IconCalendarCog, IconCheck, IconDots, IconFlag, IconLink, IconPlus, IconTarget, IconTimeline, IconTrash,
} from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import { pk, useBaselines, useTimeline } from "@/api/hooks";
import type { DepType, ScheduleResult, Timeline, TimelineDep, TimelineRow } from "@/api/types";
import { ItemPicker } from "@/components/ItemPicker";
import { ItemPreview } from "@/components/ItemPreview";
import { PageHeader } from "@/components/PageHeader";
import { ScheduleTable } from "@/components/ScheduleTable";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";
import { ResourceView } from "./ResourceView";
import { intlLocale, tx } from "@/lib/i18n";

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
  const [scheduling, setScheduling] = useState(false);
  const [view, setView] = useState<"gantt" | "resources">("gantt");
  const editable = can("contributor");
  const scrolled = useRef<string | null>(null);
  // the order comes from the saved dates only: re-sorting while a bar is dragged would move its DOM node and end the drag
  const ordered = useMemo(() => hierarchy(data?.rows ?? []), [data]);
  const rows = useMemo(() => ordered.map((r) => overrides[r.key]
    ? { ...r, start_date: overrides[r.key].start, due_date: overrides[r.key].due } : r), [ordered, overrides]);
  if (!data) return null;
  if (!data.enabled) return <><PageHeader title={tx("Timeline")} /><Text c="dimmed">{tx("This project's information model has no release or task type.")}</Text></>;
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
      notifications.show({ color: "red", title: tx("{key} not rescheduled", { key: row.key }), message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      await qc.invalidateQueries({ queryKey: pk(key, "timeline") });
      setOverrides((o) => { const n = { ...o }; delete n[row.key]; return n; });
    }
  }
  const months: { d: number; label: string }[] = [];
  for (let d = first; d <= last; d++) {
    const date = new Date(d * DAY);
    if (date.getUTCDate() === 1 || d === first) months.push({ d, label: date.toLocaleDateString(intlLocale(), { month: "short", year: "numeric", timeZone: "UTC" }) });
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
      <PageHeader title={tx("Timeline")} subtitle={tx("Schedule of releases, iterations, milestones and tasks: dependencies, critical path, baseline comparison — drag bars to reschedule")}
        actions={editable && data.task_type && (
          <Group gap="xs">
            {data.dependency_link && <Button variant="default" leftSection={<IconCalendarCog size={16} />} onClick={() => setScheduling(true)} data-testid="tl-schedule">{tx("Auto-schedule")}</Button>}
            <Button variant="default" leftSection={<IconFlag size={16} />} onClick={() => setCreating(data.release_type)} data-testid="new-plan">{tx("New plan / milestone")}</Button>
            <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(data.task_type!)} data-testid="new-task">{tx("New task")}</Button>
          </Group>
        )} />
      <SegmentedControl mb="sm" value={view} onChange={(v) => setView(v as "gantt" | "resources")} data-testid="tl-view"
        data={[{ value: "gantt", label: tx("Gantt") }, { value: "resources", label: tx("Resources") }]} />
      {view === "resources" ? <ResourceView timeline={data} /> : <>
      <Card withBorder mb="sm" padding="sm">
        <Group justify="space-between" wrap="wrap">
          <Group gap="md" wrap="wrap">
            <SegmentedControl size="xs" value={zoom} onChange={(v) => setZoom(v as Zoom)} data-testid="tl-zoom"
              data={[{ value: "weeks", label: tx("Weeks") }, { value: "months", label: tx("Months") }, { value: "quarters", label: tx("Quarters") }]} />
            <Switch size="sm" label={tx("Critical path{v}", { v: criticalCount ? ` (${criticalCount})` : "" })} checked={critical} onChange={(e) => setCritical(e.currentTarget.checked)} data-testid="tl-critical" />
            <Select size="xs" w={260} placeholder={tx("Compare with baseline…")} clearable value={baseline} onChange={setBaseline} data-testid="tl-baseline"
              data={baselines.map((b) => ({ value: b.id, label: b.name }))} />
          </Group>
          <Group gap="md">
            <Legend swatch="tl-sw-task" label={tx("task")} />
            <Legend swatch="tl-sw-plan" label={tx("release / iteration")} />
            <Legend swatch="tl-sw-ms" label={tx("milestone")} />
            {critical && <Legend swatch="tl-sw-crit" label={tx("critical")} />}
            {baseline && <Legend swatch="tl-sw-base" label={tx("baseline")} />}
          </Group>
        </Group>
      </Card>
      {data.conflicts.length > 0 && (
        <Alert color="orange" icon={<IconAlertTriangle size={16} />} mb="sm" data-testid="tl-conflicts" title={tx("{length} scheduling conflict(s)", { length: data.conflicts.length })}>
          {data.conflicts.map((c) => <Text key={`${c.item}-${c.depends_on}`} size="sm">{c.message}</Text>)}
        </Alert>
      )}
      <Card withBorder padding={0} className="gantt" data-testid="timeline">
        <div className="gantt-left">
          <div className="gantt-lhead" style={{ height: 44 }}>
            <span>{tx("Name")}</span><span>{tx("Start")}</span><span>{tx("Finish")}</span><span>%</span>
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
                    <Menu.Target><ActionIcon size="xs" variant="subtle" color="gray" aria-label={tx("Actions for {key}", { key: r.key })} data-testid={`tl-menu-${r.key}`}><IconDots size={12} /></ActionIcon></Menu.Target>
                    <Menu.Dropdown>
                      <Menu.Item leftSection={<IconLink size={14} />} onClick={() => setDepFor(r.key)} data-testid="tl-add-dep">{tx("Dependencies…")}</Menu.Item>
                      <Menu.Item onClick={() => setPreview(r.key)}>{tx("Details")}</Menu.Item>
                    </Menu.Dropdown>
                  </Menu>
                )}
              </span>
            </div>
          ))}
          {rows.length === 0 && <Text size="sm" c="dimmed" p="md">{tx("No plans or tasks yet.")}</Text>}
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
              <div className="gantt-today" style={{ left: x(today) + px / 2 }} title={tx("Today {today}", { today: data.today })} data-testid="tl-today" />
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
      </>}
      <Drawer opened={!!preview} onClose={() => setPreview(null)} position="right" size="lg" withCloseButton={false} padding="xs">
        {preview && <ItemPreview projectKey={key} itemKey={preview} model={model} onClose={() => setPreview(null)} />}
      </Drawer>
      {creating && <ItemFormModal opened onClose={() => setCreating(null)} defaultType={creating} types={[creating]} navigateOnCreate={false}
        onSaved={() => qc.invalidateQueries({ queryKey: pk(key, "timeline") })} />}
      {depFor && <DependencyModal itemKey={depFor} rows={data.rows} data={data} types={[data.task_type, data.release_type].filter(Boolean) as string[]}
        onClose={() => setDepFor(null)} />}
      {scheduling && <ScheduleModal data={data} onClose={() => setScheduling(false)} />}
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
  const tip = `${row.key} ${row.title}\n${row.kind === "milestone" ? row.due_date : `${row.start_date} → ${row.due_date}`} · ${Math.round(row.progress * 100)} %${row.slack != null ? tx(" · slack {slack} d", { slack: row.slack }) : ""}${row.baseline ? tx("\nbaseline {v} → {v1}", { v: row.baseline.start_date ?? "", v1: row.baseline.due_date ?? "" }) : ""}${row.dependencies?.length ? tx("\nafter {dependencies}", { dependencies: row.dependencies.map((d) => `${d.key} (${depShort(d.type, d.lag)})`).join(", ") }) : ""}`;
  if (row.kind === "milestone") {
    return (
      <>
        {base && <div className="tl-base-ms" style={{ left: x(base.d) + px / 2 - 5, top: top + 22 }} title={tx("Baseline {due_date}", { due_date: row.baseline?.due_date })} />}
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
        title={tx("Baseline {start_date} → {due_date}", { start_date: row.baseline?.start_date, due_date: row.baseline?.due_date })} data-testid={`tl-base-${row.key}`} />}
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

const DEP_LABEL: Record<DepType, string> = { fs: tx("Finish-to-start"), ss: tx("Start-to-start"), ff: tx("Finish-to-finish"), sf: tx("Start-to-finish") };
const DEP_HINT: Record<DepType, string> = {
  fs: tx("starts after the predecessor finishes"), ss: tx("starts when the predecessor starts"),
  ff: tx("finishes when the predecessor finishes"), sf: tx("finishes when the predecessor starts"),
};

export function depShort(type: DepType, lag: number): string {
  return `${type.toUpperCase()}${lag ? ` ${lag > 0 ? "+" : ""}${lag}d` : ""}`;
}

/** Orthogonal arrow from a predecessor end to a successor end; leaves a start edge to the left, a finish edge to the
 *  right, and arrives at a start edge from the left, at a finish edge from the right. */
function route(x1: number, y1: number, out: 1 | -1, x2: number, y2: number, approach: 1 | -1): string {
  const end = x2 - approach * 2;
  const a = x1 + out * 8;
  if ((end - a) * approach >= 4) {
    const mid = out === approach ? (approach > 0 ? Math.min(a + 6, end - 6) : Math.max(a - 6, end + 6)) : a;
    return `M${x1},${y1} H${mid} V${y2} H${end}`;
  }
  const b = x2 - approach * 12;
  const ym = y1 + (y2 > y1 ? ROW / 2 : -ROW / 2);
  return `M${x1},${y1} H${a} V${ym} H${b} V${y2} H${end}`;
}

function Dependencies({ rows, index, x, px, conflicts, critical }: {
  rows: Node[]; index: Map<string, number>; x: (d: number) => number; px: number; conflicts: Set<string>; critical: boolean;
}) {
  const paths: { d: string; cls: string; id: string; label: string | null; lx: number; ly: number; anchor: "start" | "end" }[] = [];
  const edge = (r: TimelineRow, side: "start" | "end") => {
    if (r.kind === "milestone") return x(toDay(r.due_date!)) + px / 2 + (side === "end" ? 8 : -9);
    return side === "start" ? x(toDay(r.start_date ?? r.due_date!)) : x(toDay(r.due_date ?? r.start_date!)) + px;
  };
  for (const r of rows) {
    const ti = index.get(r.key);
    if (ti === undefined || !(r.start_date || r.due_date)) continue;
    const deps = r.dependencies ?? r.depends_on.map((k) => ({ key: k, type: "fs" as DepType, lag: 0, link_id: k }));
    for (const dep of deps) {
      const pi = index.get(dep.key);
      const pr = pi !== undefined ? rows[pi] : undefined;
      if (pi === undefined || !pr || !(pr.due_date || pr.start_date)) continue;
      const fromSide = dep.type === "ss" || dep.type === "sf" ? "start" : "end";
      const toSide = dep.type === "fs" || dep.type === "ss" ? "start" : "end";
      const x1 = edge(pr, fromSide), y1 = pi * ROW + ROW / 2;
      const x2 = edge(r, toSide), y2 = ti * ROW + ROW / 2;
      const approach = toSide === "start" ? 1 : -1;
      const conflict = conflicts.has(`${r.key}>${dep.key}`);
      const crit = critical && r.critical && pr.critical;
      const label = dep.type !== "fs" || dep.lag ? depShort(dep.type, dep.lag) : null;
      paths.push({ d: route(x1, y1, fromSide === "start" ? -1 : 1, x2, y2, approach),
        cls: conflict ? "tl-dep is-conflict" : crit ? "tl-dep is-critical" : "tl-dep", id: `${dep.key}>${r.key}`,
        label, lx: x2 - approach * 14, ly: y2 - 4, anchor: approach > 0 ? "end" : "start" });
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
      {paths.filter((p) => p.label).map((p) => (
        <text key={`l${p.id}`} x={p.lx} y={p.ly} textAnchor={p.anchor} className="tl-dep-label" data-testid={`tl-deplabel-${p.id}`}>{p.label}</text>
      ))}
    </svg>
  );
}

/** Predecessors of one item: add with type and lag, change or remove existing ones. */
function DependencyModal({ itemKey, rows, types, data, onClose }: {
  itemKey: string; rows: TimelineRow[]; types: string[]; data: Timeline; onClose: () => void;
}) {
  const { key } = useProjectCtx();
  const qc = useQueryClient();
  const row = rows.find((r) => r.key === itemKey);
  const [pred, setPred] = useState<string | null>(null);
  const [type, setType] = useState<DepType>("fs");
  const [lag, setLag] = useState<number>(0);
  const [busy, setBusy] = useState(false);
  const typed = data.dependency_types;
  const attrs = (t: DepType, l: number) => typed ? { [data.dependency_type_attribute]: t, [data.dependency_lag_attribute]: l } : {};
  const refresh = () => qc.invalidateQueries({ queryKey: pk(key) });
  async function run(what: () => Promise<unknown>, message: string) {
    setBusy(true);
    try {
      await what();
      notifications.show({ color: "teal", message });
      await refresh();
    } catch (e) {
      notifications.show({ color: "red", message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }
  const typeData = (Object.keys(DEP_LABEL) as DepType[]).map((t) => ({ value: t, label: `${t.toUpperCase()} — ${DEP_LABEL[t]}` }));
  const existing = row?.dependencies ?? [];
  return (
    <Modal opened onClose={onClose} title={tx("Dependencies of {itemKey}", { itemKey: itemKey })} size="lg">
      <Stack>
        {existing.length > 0 && (
          <Table.ScrollContainer minWidth={460}>
            <Table data-testid="tl-dep-list" verticalSpacing={4}>
              <Table.Thead><Table.Tr><Table.Th>{tx("Predecessor")}</Table.Th>{typed && <><Table.Th>{tx("Type")}</Table.Th><Table.Th w={110}>{tx("Lag (days)")}</Table.Th></>}<Table.Th w={40} /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {existing.map((d) => (
                  <ExistingDep key={d.link_id} dep={d} title={rows.find((r) => r.key === d.key)?.title ?? ""} typed={typed} typeData={typeData} busy={busy}
                    onSave={(t, l) => run(() => api.patch(`/projects/${key}/links/${d.link_id}`, { attributes: attrs(t, l) }), `${itemKey} ← ${d.key}: ${depShort(t, l)}`)}
                    onRemove={() => run(() => api.del(tx("/projects/{key}/links/{link_id}", { key: key, link_id: d.link_id })), tx("Removed the dependency on {key}", { key: d.key }))} />
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        <Text size="sm" fw={600}>{tx("Add a predecessor")}</Text>
        <ItemPicker label={tx("Predecessor")} types={types} exclude={[itemKey, ...existing.map((d) => d.key)]} value={pred} onChange={setPred} testId="tl-dep-picker" />
        {typed && (
          <Group grow align="flex-end">
            <Select label={tx("Type")} data={typeData} value={type} onChange={(v) => setType((v as DepType) ?? "fs")} allowDeselect={false} data-testid="tl-dep-type" />
            <NumberInput label={tx("Lag (working days)")} value={lag} onChange={(v) => setLag(typeof v === "number" ? v : 0)} allowDecimal={false} data-testid="tl-dep-lag"
              description={tx("negative = lead")} />
          </Group>
        )}
        <Text size="sm" c="dimmed">{itemKey} {DEP_HINT[type]}{lag ? tx(" {v} {lag} working day(s)", { v: lag > 0 ? "+" : "−", lag: Math.abs(lag) }) : ""}.</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Close")}</Button>
          <Button disabled={!pred} loading={busy} data-testid="tl-dep-save"
            onClick={() => run(() => api.post(`/projects/${key}/links`, { type: data.dependency_link, source: itemKey, target: pred, attributes: attrs(type, lag) }),
              `${itemKey} ${DEP_HINT[type]} (${pred})`).then(() => { setPred(null); setLag(0); setType("fs"); })}>{tx("Add dependency")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function ExistingDep({ dep, title, typed, typeData, busy, onSave, onRemove }: {
  dep: TimelineDep; title: string; typed: boolean; typeData: { value: string; label: string }[]; busy: boolean;
  onSave: (t: DepType, lag: number) => void; onRemove: () => void;
}) {
  const [type, setType] = useState<DepType>(dep.type);
  const [lag, setLag] = useState<number>(dep.lag);
  const dirty = type !== dep.type || lag !== dep.lag;
  return (
    <Table.Tr data-testid={`tl-dep-row-${dep.key}`}>
      <Table.Td><Text size="sm"><span className="item-key">{dep.key}</span> {title}</Text></Table.Td>
      {typed && <>
        <Table.Td><Select size="xs" data={typeData} value={type} onChange={(v) => setType((v as DepType) ?? "fs")} allowDeselect={false} w={190} /></Table.Td>
        <Table.Td><NumberInput size="xs" value={lag} onChange={(v) => setLag(typeof v === "number" ? v : 0)} allowDecimal={false} w={90} /></Table.Td>
      </>}
      <Table.Td>
        <Group gap={2} wrap="nowrap">
          {dirty && <ActionIcon size="sm" color="teal" variant="light" onClick={() => onSave(type, lag)} disabled={busy} aria-label={tx("Save")} data-testid={`tl-dep-update-${dep.key}`}><IconCheck size={14} /></ActionIcon>}
          <ActionIcon size="sm" color="red" variant="subtle" onClick={onRemove} disabled={busy} aria-label={tx("Remove dependency on {key}", { key: dep.key })} data-testid={`tl-dep-remove-${dep.key}`}><IconTrash size={14} /></ActionIcon>
        </Group>
      </Table.Td>
    </Table.Tr>
  );
}

/** Auto-scheduling along the dependencies with a preview (like the bulk edit): push conflicts out or plan ASAP. */
function ScheduleModal({ data, onClose }: { data: Timeline; onClose: () => void }) {
  const { key } = useProjectCtx();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"push" | "asap">("push");
  const [plan, setPlan] = useState<string | null>(null);
  const [result, setResult] = useState<ScheduleResult | null>(null);
  const [busy, setBusy] = useState(false);
  const plans = data.rows.filter((r) => r.kind === "release" || r.kind === "iteration").map((r) => ({ value: r.key, label: `${r.key} ${r.title}` }));
  async function run(dryRun: boolean) {
    setBusy(true);
    try {
      const r = await api.post<ScheduleResult>(`/projects/${key}/timeline/schedule`, { mode, plan, dry_run: dryRun });
      if (dryRun) setResult(r);
      else {
        notifications.show({ color: "teal", message: tx("Scheduled: {ok} moved{v}", { ok: r.summary.ok ?? 0, v: r.summary.skipped ? tx(", {skipped} skipped", { skipped: r.summary.skipped }) : "" }) });
        await qc.invalidateQueries({ queryKey: pk(key) });
        onClose();
      }
    } catch (e) {
      notifications.show({ color: "red", message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal opened onClose={onClose} title={tx("Auto-schedule along the dependencies")} size="xl">
      <Stack data-testid="tl-sched-modal">
        <SegmentedControl value={mode} onChange={(v) => { setMode(v as "push" | "asap"); setResult(null); }} data-testid="tl-sched-mode"
          data={[{ value: "push", label: tx("Resolve conflicts (move later only)") }, { value: "asap", label: tx("As soon as possible") }]} />
        <Select label={tx("Only work in plan")} placeholder={tx("All tasks and milestones")} clearable data={plans} value={plan} onChange={(v) => { setPlan(v); setResult(null); }} />
        <Text size="sm" c="dimmed">{tx("Tasks and milestones move by working days and keep their duration. Plans, frozen, started and finished items keep their dates.")}</Text>
        {result && <ScheduleTable result={result} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={() => run(true)} loading={busy && !result} data-testid="tl-sched-preview">{tx("Preview")}</Button>
          <Button onClick={() => run(false)} disabled={!result || result.moves.length === 0} loading={busy && !!result} data-testid="tl-sched-apply">{tx("Apply")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
