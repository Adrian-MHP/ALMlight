import { useMemo, useState } from "react";
import {
  Badge, Button, Card, Grid, Group, Progress, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput,
  Tooltip,
} from "@mantine/core";
import { LineChart } from "@mantine/charts";
import { useElementSize } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { DndContext, DragOverlay, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { IconFlag, IconPlus, IconSearch, IconTimeline } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "@/api/client";
import { pk, useItems, usePlan, usePlans, useProjectMutation } from "@/api/hooks";
import type { Item, PlanDetail, PlanSummary } from "@/api/types";
import { ItemPicker } from "@/components/ItemPicker";
import { PageHeader } from "@/components/PageHeader";
import { TypeBadge } from "@/components/badges";
import { stateColor } from "@/lib/model";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";
import { intlLocale, tm, tx } from "@/lib/i18n";

const STATUS: Record<PlanSummary["status"], { color: string; label: string }> = {
  on_track: { color: "green", label: tx("on track") }, at_risk: { color: "yellow", label: tx("at risk") },
  overdue: { color: "red", label: tx("overdue") }, done: { color: "gray", label: tx("done") },
};
const KIND_LABEL: Record<string, string> = { release: tx("Release"), iteration: tx("Iteration"), milestone: tx("Milestone") };

function day(s: string | null): number | null {
  return s ? new Date(`${s}T00:00:00Z`).getTime() : null;
}

/** Month starts between two instants, thinned out so that at most ``fit`` labels are shown (about 60 px each). */
function months(min: number, max: number, fit = 12): { t: number; label: string }[] {
  const out: { t: number; label: string }[] = [];
  const d = new Date(min);
  let cur = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
  while (cur < max) {
    const m = new Date(cur);
    out.push({ t: cur, label: m.toLocaleDateString(intlLocale(), { month: "short", ...(m.getUTCMonth() === 0 ? { year: "numeric" } : {}), timeZone: "UTC" }) });
    cur = Date.UTC(m.getUTCFullYear(), m.getUTCMonth() + 1, 1);
  }
  const step = Math.max(1, Math.ceil(out.length / Math.max(1, fit)));
  return out.filter((_, i) => i % step === 0);
}

/** Order plans as a tree: top-level plans, each followed by its sub-plans. */
function tree(plans: PlanSummary[]): { plan: PlanSummary; depth: number }[] {
  const byKey = new Map(plans.map((p) => [p.key, p]));
  const out: { plan: PlanSummary; depth: number }[] = [];
  const seen = new Set<string>();
  const walk = (p: PlanSummary, depth: number) => {
    if (seen.has(p.key)) return;
    seen.add(p.key);
    out.push({ plan: p, depth });
    for (const c of p.children) { const child = byKey.get(c); if (child) walk(child, depth + 1); }
  };
  for (const p of plans) if (!p.parent || !byKey.has(p.parent)) walk(p, 0);
  return out;
}

function LoadBar({ estimate, capacity }: { estimate: number; capacity: number | null }) {
  if (!capacity) return estimate ? <Text size="xs" c="dimmed">{tx("{estimate} estimated", { estimate: estimate })}</Text> : null;
  const load = estimate / capacity;
  return (
    <Tooltip label={tx("{estimate} of {capacity} capacity planned ({Math} %)", { estimate: estimate, capacity: capacity, Math: Math.round(load * 100) })}>
      <div data-testid="load-bar">
        <Group justify="space-between" gap={4}><Text size="xs" c="dimmed">{tx("Load")}</Text><Text size="xs" c={load > 1 ? "red" : "dimmed"} fw={load > 1 ? 700 : undefined}>{estimate} / {capacity}</Text></Group>
        <Progress size="sm" value={Math.min(100, load * 100)} color={load > 1 ? "red" : load > 0.85 ? "yellow" : "teal"} />
      </div>
    </Tooltip>
  );
}

/** Polarion-style plans: release / iteration / milestone hierarchy with progress, capacity, burn-up and a planning board. */
export function PlansPage() {
  const { key, model, can } = useProjectCtx();
  const { data } = usePlans(key);
  const [params, setParams] = useSearchParams();
  const selected = params.get("release");
  const [creating, setCreating] = useState(false);
  const axis = useElementSize();
  const rows = useMemo(() => tree(data?.releases ?? []), [data]);
  if (!data) return null;
  if (!data.enabled) {
    return <><PageHeader title={tx("Plans")} /><Text c="dimmed">{tx("This project's information model has no release type. A manager can take it over from the template (Settings → Information model).")}</Text></>;
  }
  const dated = data.releases.filter((r) => r.start_date || r.due_date);
  const min = Math.min(...dated.map((r) => day(r.start_date ?? r.due_date)!), Date.now());
  const max = Math.max(...dated.map((r) => day(r.due_date ?? r.start_date)!), Date.now() + 86400000);
  const pos = (t: number) => `${((t - min) / (max - min)) * 100}%`;
  return (
    <>
      <PageHeader title={tx("Plans")} subtitle={tx("Releases, iterations and milestones: planned work, capacity, progress and schedule status")}
        actions={
          <Group gap="xs">
            <Button variant="default" component={Link} to={`/p/${key}/timeline`} leftSection={<IconTimeline size={16} />}>{tx("Timeline")}</Button>
            {can("contributor") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-release">{tx("New {type_label}", { type_label: tm(data.type_label) })}</Button>}
          </Group>
        } />
      <Card withBorder mb="md" data-testid="plan-timeline">
        <Text fw={600} mb="sm">{tx("Timeline")}</Text>
        <div className="plan-timeline">
          <div className="plan-axis">
            <span />
            <div className="plan-months" ref={axis.ref}>
              {months(min, max, Math.floor((axis.width || 720) / 60)).map((m) => <span key={m.t} className="plan-month" style={{ left: pos(m.t) }}>{m.label}</span>)}
            </div>
          </div>
          {rows.map(({ plan: r, depth }) => {
            const s = day(r.start_date), e = day(r.due_date);
            return (
              <div key={r.key} className="plan-row clickable" onClick={() => setParams({ release: r.key })}>
                <Text size="xs" className="plan-label" truncate style={{ paddingLeft: depth * 12 }}><b className="mono">{r.key}</b> {r.title}</Text>
                <div className="plan-track">
                  <div className="plan-today" style={{ left: pos(Date.now()) }} title={tx("Today")} />
                  {r.kind === "milestone" && e ? (
                    <Tooltip label={tx("Milestone {due_date}", { due_date: r.due_date })}><div className="plan-ms" style={{ left: `calc(${pos(e)} - 6px)` }} /></Tooltip>
                  ) : s && e ? (
                    <Tooltip label={tx("{start_date} → {due_date} · {Math} % done", { start_date: r.start_date, due_date: r.due_date, Math: Math.round(r.progress * 100) })}>
                      <div className={`plan-bar${r.kind === "iteration" ? " is-iteration" : ""}`} style={{ left: pos(s), width: `calc(${pos(e)} - ${pos(s)})`, borderColor: `var(--mantine-color-${STATUS[r.status].color}-6)` }}>
                        <div className="plan-fill" style={{ width: `${r.progress * 100}%` }} />
                      </div>
                    </Tooltip>
                  ) : <Text size="xs" c="dimmed">{tx("no dates")}</Text>}
                </div>
              </div>
            );
          })}
        </div>
      </Card>
      <Grid>
        <Grid.Col span={{ base: 12, lg: selected ? 4 : 12 }}>
          <Stack gap="xs">
            {rows.map(({ plan: r, depth }) => (
              <Card key={r.key} withBorder padding="sm" className="clickable" onClick={() => setParams({ release: r.key })} ml={depth * 18}
                style={{ borderColor: selected === r.key ? "var(--mantine-primary-color-filled)" : undefined }} data-testid={`release-${r.key}`}>
                <Group justify="space-between" wrap="nowrap" align="flex-start">
                  <Text fw={600} truncate style={{ minWidth: 0 }}>
                    {r.kind === "milestone" && <IconFlag size={14} style={{ marginRight: 4, verticalAlign: -2 }} />}
                    <span className="item-key">{r.key}</span> {r.title}
                  </Text>
                  <Badge className="badge-keep" color={STATUS[r.status].color} data-testid={`release-status-${r.key}`}>{STATUS[r.status].label}</Badge>
                </Group>
                <Group gap={6} mt={2} wrap="wrap">
                  <Badge size="xs" variant="outline" color="gray" className="badge-keep">{KIND_LABEL[r.kind] ?? r.kind}</Badge>
                  <Badge size="xs" variant="light" className="badge-keep" color={stateColor(r.state_color, null)}>{tm(r.state_label)}</Badge>
                  <Text size="xs" c="dimmed">{tx("{v} · {done} of {total} done", { v: r.kind === "milestone" ? r.due_date : `${r.start_date ?? "?"} → ${r.due_date ?? "?"}`, done: r.done, total: r.total })}</Text>
                </Group>
                {r.kind !== "milestone" && (
                  <>
                    <Progress.Root mt={6} size="lg">
                      <Progress.Section value={r.progress * 100} color="teal"><Progress.Label>{Math.round(r.progress * 100)} %</Progress.Label></Progress.Section>
                    </Progress.Root>
                    {r.expected != null && <Text size="xs" c="dimmed" mt={2}>{tx("Expected by today: {Math} %", { Math: Math.round(r.expected * 100) })}</Text>}
                    <LoadBar estimate={r.estimate} capacity={r.capacity} />
                  </>
                )}
              </Card>
            ))}
            {data.releases.length === 0 && <Text c="dimmed">{tx("No releases yet.")}</Text>}
          </Stack>
        </Grid.Col>
        {selected && <Grid.Col span={{ base: 12, lg: 8 }}><PlanDetailCard releaseKey={selected} plannable={data.plannable_types ?? []} /></Grid.Col>}
      </Grid>
      {model.releaseType && <ItemFormModal opened={creating} onClose={() => setCreating(false)} defaultType={model.releaseType.key} types={[model.releaseType.key]} />}
    </>
  );
}

function PlanDetailCard({ releaseKey, plannable }: { releaseKey: string; plannable: string[] }) {
  const { key } = useProjectCtx();
  const { data } = usePlan(key, releaseKey);
  const [tab, setTab] = useState<string | null>("overview");
  const [metric, setMetric] = useState<"count" | "estimate">("count");
  const [chart, setChart] = useState<"up" | "down">("up");
  if (!data) return null;
  const today = [...data.burnup].reverse().find((p) => !p.future)?.date.slice(5);
  const series = data.burnup.map((p) => {
    const done = metric === "count" ? p.done : p.done_estimate;
    const scope = metric === "count" ? p.scope : p.scope_estimate;
    const remaining = metric === "count" ? p.remaining : p.remaining_estimate;
    return { date: p.date.slice(5), done: p.future ? null : done, scope, remaining: p.future ? null : remaining };
  });
  return (
    <Card withBorder data-testid="plan-detail">
      <Group justify="space-between" mb="xs" wrap="nowrap" align="flex-start">
        <div style={{ minWidth: 0 }}>
          <Text fw={650} size="lg"><Link to={`/p/${key}/items/${data.key}`} className="item-key">{data.key}</Link> {data.title}</Text>
          {data.goal && <Text size="sm" c="dimmed">{data.goal}</Text>}
          {data.parent && <Text size="xs" c="dimmed">{tx("Part of {parent}", { parent: data.parent })}</Text>}
        </div>
        <Badge size="lg" className="badge-keep" color={STATUS[data.status].color}>{STATUS[data.status].label}</Badge>
      </Group>
      <Tabs value={tab} onChange={setTab} keepMounted={false}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="overview" data-testid="plan-tab-overview">{tx("Overview")}</Tabs.Tab>
          <Tabs.Tab value="items" data-testid="plan-tab-items">{tx("Planned items ({total})", { total: data.total })}</Tabs.Tab>
          <Tabs.Tab value="planning" data-testid="plan-tab-planning">{tx("Planning board")}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview">
          <SimpleGrid cols={{ base: 2, sm: 4 }} mb="sm">
            <Kpi label={tx("Done")} value={`${data.done} / ${data.total}`} />
            <Kpi label={tx("Estimate done")} value={`${data.estimate_done} / ${data.estimate}`} />
            <Kpi label={tx("Capacity")} value={data.capacity ? `${data.capacity}` : "–"} />
            <Kpi label={tx("Load")} value={data.load != null ? `${Math.round(data.load * 100)} %` : "–"} color={data.load && data.load > 1 ? "red" : undefined} />
          </SimpleGrid>
          <Group justify="space-between" mb={4}>
            <SegmentedControl size="xs" value={chart} onChange={(v) => setChart(v as "up" | "down")} data={[{ value: "up", label: tx("Burn-up") }, { value: "down", label: tx("Burn-down") }]} data-testid="plan-chart-kind" />
            <SegmentedControl size="xs" value={metric} onChange={(v) => setMetric(v as "count" | "estimate")} data={[{ value: "count", label: tx("Items") }, { value: "estimate", label: tx("Estimate") }]} data-testid="plan-chart-metric" />
          </Group>
          {data.burnup.length > 1 && (
            <LineChart h={220} mb="md" data={series} dataKey="date"
              series={chart === "up" ? [{ name: "done", color: "teal.6", label: tx("Done") }, { name: "scope", color: "gray.5", label: tx("Scope") }]
                : [{ name: "remaining", color: "orange.6", label: tx("Remaining") }]}
              curveType="stepAfter" withDots={false} connectNulls={false} tickLine="none" gridAxis="y" withLegend legendProps={{ verticalAlign: "top", height: 30 }}
              referenceLines={today ? [{ x: today, label: tx("Today"), color: "red.5" }] : []} data-testid="burnup" />
          )}
          {data.child_plans.length > 0 && (
            <Table.ScrollContainer minWidth={560}>
              <Table data-testid="child-plans">
                <Table.Thead><Table.Tr><Table.Th>{tx("Sub-plan")}</Table.Th><Table.Th>{tx("Dates")}</Table.Th><Table.Th>{tx("Progress")}</Table.Th><Table.Th>{tx("Load")}</Table.Th><Table.Th>{tx("Status")}</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {data.child_plans.map((c) => (
                    <Table.Tr key={c.key}>
                      <Table.Td><Text size="sm"><span className="item-key">{c.key}</span> {c.title}</Text><Text size="xs" c="dimmed">{KIND_LABEL[c.kind] ?? c.kind}</Text></Table.Td>
                      <Table.Td><Text size="xs">{c.kind === "milestone" ? c.due_date : `${c.start_date ?? "?"} → ${c.due_date ?? "?"}`}</Text></Table.Td>
                      <Table.Td w={140}>{c.kind !== "milestone" && <Progress value={c.progress * 100} color="teal" />}</Table.Td>
                      <Table.Td w={150}><LoadBar estimate={c.estimate} capacity={c.capacity} /></Table.Td>
                      <Table.Td><Badge size="sm" className="badge-keep" color={STATUS[c.status].color}>{STATUS[c.status].label}</Badge></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </Tabs.Panel>
        <Tabs.Panel value="items"><PlanItems data={data} plannable={plannable} /></Tabs.Panel>
        <Tabs.Panel value="planning"><PlanningBoard plan={data} plannable={plannable} /></Tabs.Panel>
      </Tabs>
    </Card>
  );
}

function Kpi({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Card withBorder padding="xs">
      <Text size="xs" tt="uppercase" fw={600} c="dimmed">{label}</Text>
      <Text fz={20} fw={650} c={color}>{value}</Text>
    </Card>
  );
}

function PlanItems({ data, plannable }: { data: PlanDetail; plannable: string[] }) {
  const { key, model, can } = useProjectCtx();
  const [adding, setAdding] = useState<string | null>(null);
  const add = useProjectMutation(key, () => api.post(`/projects/${key}/links`, { type: model.config.semantics.planned_link, source: adding, target: data.key }),
    { success: tx("Planned into the release"), onSuccess: () => setAdding(null) });
  return (
    <>
      {can("contributor") && (
        <Group align="flex-end" mb="sm">
          <div style={{ flex: 1 }}><ItemPicker label={tx("Plan an item into this plan")} types={plannable} value={adding} onChange={setAdding} testId="plan-item"
            exclude={[data.key, ...data.items.map((i) => i.key)]} /></div>
          <Button onClick={() => add.mutate(undefined)} disabled={!adding} loading={add.isPending} data-testid="plan-add">{tx("Plan")}</Button>
        </Group>
      )}
      <Table.ScrollContainer minWidth={620}>
        <Table data-testid="plan-items">
          <Table.Thead><Table.Tr><Table.Th>{tx("Item")}</Table.Th><Table.Th>{tx("Type")}</Table.Th><Table.Th>{tx("Plan")}</Table.Th><Table.Th ta="right">{tx("Estimate")}</Table.Th><Table.Th>{tx("State")}</Table.Th><Table.Th>{tx("Owner")}</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {data.items.map((i) => (
              <Table.Tr key={i.key}>
                <Table.Td><Link to={`/p/${key}/items/${i.key}`} className="item-key">{i.key}</Link> <Text span size="sm">{i.title}</Text></Table.Td>
                <Table.Td><Text size="sm">{tm(i.type_label)}</Text></Table.Td>
                <Table.Td><Text size="xs" className="mono">{i.plan}</Text></Table.Td>
                <Table.Td ta="right"><Text size="sm">{i.estimate ?? ""}</Text></Table.Td>
                <Table.Td><Badge size="sm" variant={i.done ? "filled" : "light"} color={stateColor(i.state_color, i.state_category)}>{i.state ?? "–"}</Badge></Table.Td>
                <Table.Td><Text size="sm">{i.owner?.display_name}</Text></Table.Td>
              </Table.Tr>
            ))}
            {data.items.length === 0 && <Table.Tr><Table.Td colSpan={6}><Text c="dimmed" ta="center" py="md">{tx("Nothing planned yet — use the planning board.")}</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </>
  );
}

const BACKLOG = "__backlog";

/** Polarion "Planning" view: the backlog (unplanned work) beside the plan and its sub-plans; drag to plan or move. */
function PlanningBoard({ plan, plannable }: { plan: PlanDetail; plannable: string[] }) {
  const { key, model, can } = useProjectCtx();
  const qc = useQueryClient();
  const estKey = model.config.semantics.estimate_field ?? "estimate";
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>("__req");
  const types = typeFilter === "__req" ? plannable.filter((t) => ["requirement", "change"].includes(model.type(t)?.category ?? ""))
    : typeFilter ? [typeFilter] : plannable;
  const backlog = useItems(key, { q: search || undefined, type: types.length ? types : plannable, limit: 200, sort: "key",
    conditions: [{ field: "release", op: "exists", values: [true], not: true }] }).data?.items ?? [];
  const columns = [plan, ...plan.child_plans.filter((c) => c.kind !== "milestone")];
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const [dragging, setDragging] = useState<{ key: string; title: string } | null>(null);
  const editable = can("contributor");
  async function onDragEnd(e: DragEndEvent) {
    setDragging(null);
    if (!e.over) return;
    const d = e.active.data.current as { key: string; from: string };
    const to = String(e.over.id);
    if (to === d.from) return;
    try {
      if (to === BACKLOG) {
        await api.post(`/projects/${key}/items/bulk`, { keys: [d.key], action: "unplan", release: d.from, dry_run: false });
        notifications.show({ color: "teal", message: tx("{key} back to the backlog", { key: d.key }) });
      } else {
        const res = await api.post<{ results: { status: string; message: string | null }[] }>(`/projects/${key}/items/bulk`,
          { keys: [d.key], action: "plan", release: to, from_release: d.from === BACKLOG ? null : d.from, dry_run: false });
        const r = res.results[0];
        notifications.show({ color: r?.status === "skipped" ? "orange" : "teal", message: r?.status === "skipped" ? `${d.key}: ${r.message}` : tx("{key} planned into {to}", { key: d.key, to: to }) });
      }
    } catch (err) {
      notifications.show({ color: "red", message: err instanceof ApiError ? err.message : String(err) });
    }
    qc.invalidateQueries({ queryKey: pk(key) });
  }
  const est = (v: unknown) => (typeof v === "number" ? v : 0);
  return (
    <DndContext sensors={sensors} onDragStart={(e) => setDragging(e.active.data.current as { key: string; title: string })} onDragEnd={onDragEnd} onDragCancel={() => setDragging(null)}>
      <div className="pb" style={{ gridTemplateColumns: `minmax(220px, 1fr) repeat(${columns.length}, minmax(200px, 1fr))` }} data-testid="planning-board">
        <PlanColumn id={BACKLOG} title={tx("Backlog")} subtitle={tx("{length} unplanned", { length: backlog.length })}>
          <TextInput size="xs" placeholder={tx("Search…")} leftSection={<IconSearch size={12} />} value={search} onChange={(e) => setSearch(e.currentTarget.value)} mb={4} data-testid="backlog-search" />
          <Select size="xs" placeholder={tx("All plannable types")} value={typeFilter} onChange={setTypeFilter} mb={6} clearable data-testid="backlog-type"
            data={[{ value: "__req", label: tx("Requirements & changes") }, ...plannable.map((t) => ({ value: t, label: model.typeLabel(t) }))]} />
          {backlog.map((i: Item) => <PlanCard key={i.key} id={i.key} from={BACKLOG} title={i.title} typeKey={i.type_key} estimate={i.fields[estKey]} disabled={!editable} />)}
        </PlanColumn>
        {columns.map((c) => {
          const items = plan.items.filter((i) => i.plan === c.key);
          const sum = items.reduce((s, i) => s + est(i.estimate), 0);
          return (
            <PlanColumn key={c.key} id={c.key} title={`${c.key} ${c.title}`} subtitle={`${c.start_date ?? "?"} → ${c.due_date ?? "?"}`}
              footer={<LoadBar estimate={c.key === plan.key ? sum : c.estimate} capacity={c.key === plan.key && plan.child_plans.length ? null : c.capacity} />}>
              {items.map((i) => <PlanCard key={i.key} id={i.key} from={c.key} title={i.title} typeKey={i.type_key} estimate={i.estimate} done={i.done} disabled={!editable} />)}
            </PlanColumn>
          );
        })}
      </div>
      <DragOverlay>{dragging && <Card withBorder padding="xs" shadow="md"><Text size="xs" className="item-key">{dragging.key}</Text><Text size="sm" lineClamp={1}>{dragging.title}</Text></Card>}</DragOverlay>
    </DndContext>
  );
}

function PlanColumn({ id, title, subtitle, footer, children }: { id: string; title: string; subtitle?: string; footer?: React.ReactNode; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div ref={setNodeRef} className={`pb-col${isOver ? " is-over" : ""}`} data-testid={`pb-col-${id}`}>
      <Text size="sm" fw={600} lineClamp={1} title={title}>{title}</Text>
      {subtitle && <Text size="xs" c="dimmed" mb={4}>{subtitle}</Text>}
      {footer && <div style={{ marginBottom: 6 }}>{footer}</div>}
      <ScrollArea.Autosize mah={460}><Stack gap={6}>{children}</Stack></ScrollArea.Autosize>
    </div>
  );
}

function PlanCard({ id, from, title, typeKey, estimate, done, disabled }: { id: string; from: string; title: string; typeKey: string; estimate: unknown; done?: boolean; disabled: boolean }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `${from}:${id}`, data: { key: id, from, title }, disabled });
  return (
    <div ref={setNodeRef} {...attributes} {...listeners} style={{ opacity: isDragging ? 0.35 : 1 }} data-testid={`pb-card-${id}`}>
      <Card withBorder padding={6} className="kb-card" style={{ borderLeftColor: done ? "var(--mantine-color-green-6)" : "var(--mantine-color-gray-4)" }}>
        <Group justify="space-between" gap={4} wrap="nowrap">
          <Text size="xs" className="item-key">{id}</Text>
          {typeof estimate === "number" && <Badge size="xs" variant="light" color="cyan">{estimate}</Badge>}
        </Group>
        <Text size="xs" lineClamp={2}>{title}</Text>
        <TypeBadge typeKey={typeKey} />
      </Card>
    </div>
  );
}
