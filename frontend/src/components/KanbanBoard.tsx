import { useMemo, useRef, useState } from "react";
import { ActionIcon, Avatar, Badge, Card, Drawer, Group, Loader, ScrollArea, Stack, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, useDraggable, useDroppable, useSensor, useSensors,
  type DragEndEvent, type DragStartEvent,
} from "@dnd-kit/core";
import { IconChevronDown, IconChevronRight, IconLock } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import { pk, useDirectory, useItems } from "@/api/hooks";
import type { BoardConfig, Item, TransitionDef, UserRef } from "@/api/types";
import { ItemPreview } from "@/components/ItemPreview";
import { ActionPrompt } from "@/components/PasswordPrompt";
import { TypeBadge } from "@/components/badges";
import { stateColor, type Model } from "@/lib/model";
import { topLeaves } from "@/lib/queryFields";
import { tx } from "@/lib/i18n";

export interface Group_ { value: string; label: string; color?: string }

const NONE = "__none";

/** Values of a grouping (columns or swimlanes) and how to read an item's value. */
function grouping(by: string, model: Model, items: Item[], users: UserRef[], releases: Item[], plans: Record<string, string>, types: string[]) {
  if (by === "state") {
    const seen = new Map<string, Group_>();
    for (const t of types.length ? types : Array.from(new Set(items.map((i) => i.type_key)))) {
      for (const s of model.workflow(t)?.states ?? []) if (!seen.has(s.key)) seen.set(s.key, { value: s.key, label: s.label, color: stateColor(s.color, s.category) });
    }
    return { groups: [...seen.values()], of: (i: Item) => i.lifecycle.state ?? NONE, editable: true };
  }
  if (by === "owner") {
    const ids = Array.from(new Set(items.map((i) => i.owner?.id).filter(Boolean))) as string[];
    return { groups: [...ids.map((id) => ({ value: id, label: users.find((u) => u.id === id)?.display_name ?? id })), { value: NONE, label: tx("Unassigned") }],
      of: (i: Item) => i.owner?.id ?? NONE, editable: true };
  }
  if (by === "release") {
    return { groups: [...releases.map((r) => ({ value: r.key, label: `${r.key} ${r.title}` })), { value: NONE, label: tx("Not planned") }],
      of: (i: Item) => plans[i.key] ?? NONE, editable: true };
  }
  if (by === "type") {
    const ts = types.length ? types : Array.from(new Set(items.map((i) => i.type_key)));
    return { groups: ts.map((t) => ({ value: t, label: model.typeLabel(t) })), of: (i: Item) => i.type_key, editable: false };
  }
  const key = by.slice(6);
  const def = (types.length ? types : model.config.item_types.map((t) => t.key)).map((t) => model.field(t, key)).find(Boolean);
  if (def?.type === "boolean") {
    return { groups: [{ value: "true", label: tx("{label}: yes", { label: def.label }) }, { value: "false", label: tx("{label}: no", { label: def.label }) }],
      of: (i: Item) => (i.fields[key] ? "true" : "false"), editable: true, field: key, def };
  }
  if (def?.type === "user") {
    return { groups: [...users.map((u) => ({ value: u.id, label: u.display_name })), { value: NONE, label: tx("Nobody") }],
      of: (i: Item) => (i.fields[key] as string) ?? NONE, editable: true, field: key, def };
  }
  return { groups: [...(def?.options ?? []).map((o) => ({ value: o.key, label: o.label, color: o.color ?? undefined })), { value: NONE, label: tx("No {label}", { label: def?.label.toLowerCase() ?? key }) }],
    of: (i: Item) => (i.fields[key] as string) ?? NONE, editable: !(def?.formula || def?.classify), field: key, def };
}

interface Pending { item: Item; transition: TransitionDef; lane?: { by: string; value: string } }

/** A Kanban board over a filtered set of items; moving a card runs the transition or field change behind it. */
const DEFAULTS: BoardConfig = { types: [], q: null, conditions: [], columns_by: "state", swimlanes_by: null, hidden_columns: [],
  column_order: [], wip: {}, card_fields: [] };

export function KanbanBoard({ projectKey, model, config: raw, canEdit, testId = "board" }: {
  projectKey: string; model: Model; config: Partial<BoardConfig>; canEdit: boolean; testId?: string;
}) {
  const config: BoardConfig = useMemo(() => ({ ...DEFAULTS, ...raw }), [raw]);
  const qc = useQueryClient();
  const users = useDirectory().data ?? [];
  const { data, isLoading } = useItems(projectKey, { type: config.types.length ? config.types : undefined, q: config.q || undefined,
    conditions: config.conditions, limit: 1000, sort: "key" });
  const frozen = useRef<Item[] | null>(null);  // the card list stays put while a card is dragged (live refreshes wait)
  const items = frozen.current ?? data?.items ?? [];
  const needsPlans = config.columns_by === "release" || config.swimlanes_by === "release";
  const releaseCond = topLeaves(config.conditions).find((c) => c.field === "release" && c.op === "in" && !c.not);
  const releasesAll = useItems(projectKey, { type: model.releaseType ? [model.releaseType.key] : [], limit: 300 }, needsPlans && !!model.releaseType).data?.items ?? [];
  const releases = releaseCond ? releasesAll.filter((r) => (releaseCond.values as string[]).includes(r.key))
    : releasesAll.filter((r) => !["closed", "obsolete"].includes(r.lifecycle.category ?? ""));
  const plans = usePlanOf(projectKey, needsPlans ? releasesAll : []);
  const cols = useMemo(() => grouping(config.columns_by, model, items, users, releases, plans, config.types),
    [config, model, items, users, releases, plans]);
  const lanes = useMemo(() => config.swimlanes_by ? grouping(config.swimlanes_by, model, items, users, releases, plans, config.types) : null,
    [config, model, items, users, releases, plans]);
  const order = (gs: Group_[]) => {
    const pos = new Map(config.column_order.map((v, i) => [v, i]));
    return [...gs].filter((g) => !config.hidden_columns.includes(g.value)).sort((a, b) => (pos.get(a.value) ?? 999) - (pos.get(b.value) ?? 999));
  };
  const columns = order(cols.groups);
  const laneGroups = lanes ? lanes.groups.filter((l) => items.some((i) => lanes.of(i) === l.value)) : [{ value: "all", label: "" }];
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [dragging, setDragging] = useState<Item | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor));

  const transitionTo = (item: Item, target: string): TransitionDef | undefined =>
    model.workflow(item.type_key)?.transitions.find((t) => t.from.includes(item.lifecycle.state ?? "") && t.to === target);
  const validTarget = (item: Item, col: string) => {
    if (!cols.editable) return cols.of(item) === col;
    if (config.columns_by !== "state") return true;
    return col === item.lifecycle.state || !!transitionTo(item, col);
  };
  const refresh = () => { qc.invalidateQueries({ queryKey: pk(projectKey) }); };

  async function applyGroup(item: Item, by: string, value: string, field?: string) {
    if (by === "owner") await api.patch(`/projects/${projectKey}/items/${item.key}`, { owner_id: value === NONE ? null : value });
    else if (by === "release") {
      const from = plans[item.key];
      if (value === NONE) {
        if (from) await api.post(`/projects/${projectKey}/items/bulk`, { keys: [item.key], action: "unplan", release: from, dry_run: false });
      } else {
        const res = await api.post<{ results: { status: string; message: string | null }[] }>(`/projects/${projectKey}/items/bulk`,
          { keys: [item.key], action: "plan", release: value, from_release: from ?? null, dry_run: false });
        if (res.results[0]?.status === "skipped") throw new Error(res.results[0].message ?? tx("Not possible"));
      }
    } else if (field) {
      const v = value === NONE ? null : value === "true" ? true : value === "false" ? false : value;
      await api.patch(`/projects/${projectKey}/items/${item.key}`, { fields: { [field]: v } });
    }
  }
  async function runTransition(item: Item, t: TransitionDef, extra: { comment?: string; password?: string } = {}) {
    const res = await api.post<{ status: string }>(`/projects/${projectKey}/items/${item.key}/transitions/${t.key}`,
      { comment: extra.comment || null, password: extra.password || null });
    notifications.show({ color: "teal", message: res.status === "approval_requested" ? tx("{key}: approval requested ({label})", { key: item.key, label: t.label }) : `${item.key}: ${t.label}` });
  }
  async function move(item: Item, col: string, lane: string | null) {
    const sameCol = cols.of(item) === col;
    const sameLane = !lanes || lane === null || lanes.of(item) === lane;
    if (sameCol && sameLane) return;
    if ((!sameCol && !cols.editable) || (!sameLane && lanes && !lanes.editable)) {
      notifications.show({ color: "orange", message: tx("This grouping cannot be changed by moving cards") });
      return;
    }
    setBusy(item.key);
    try {
      if (!sameLane && lanes && lane !== null) await applyGroup(item, config.swimlanes_by!, lane, (lanes as { field?: string }).field);
      if (!sameCol) {
        if (config.columns_by === "state") {
          const t = transitionTo(item, col);
          if (!t) { notifications.show({ color: "orange", message: tx("No transition from {label} to {label1}", { label: model.state(item.type_key, item.lifecycle.state)?.label, label1: model.state(item.type_key, col)?.label ?? col }) }); return; }
          if (t.signature || t.comment_required) { setPending({ item, transition: t }); return; }
          await runTransition(item, t);
        } else {
          await applyGroup(item, config.columns_by, col, (cols as { field?: string }).field);
        }
      }
    } catch (e) {
      notifications.show({ color: "red", title: tx("{key} not moved", { key: item.key }), message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(null);
      refresh();
    }
  }
  function onDragStart(e: DragStartEvent) { frozen.current = data?.items ?? []; setDragging((e.active.data.current as { item: Item }).item); }
  function onDragEnd(e: DragEndEvent) {
    const item = (e.active.data.current as { item: Item }).item;
    frozen.current = null;
    setDragging(null);
    if (!e.over) return;
    const [col, lane] = String(e.over.id).split("|");
    move(item, col, lanes ? lane : null);
  }
  if (isLoading) return <Loader />;
  const cardFields = config.card_fields.map((k) => ({ key: k, def: (config.types.length ? config.types : model.config.item_types.map((t) => t.key)).map((t) => model.field(t, k)).find(Boolean) }));
  return (
    <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => { frozen.current = null; setDragging(null); }}>
      <ScrollArea type="auto" offsetScrollbars data-testid={testId}>
        <div className="kb" style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(230px, 1fr))` }}>
          {columns.map((c) => {
            const n = items.filter((i) => cols.of(i) === c.value).length;
            const limit = config.wip[c.value];
            return (
              <div key={c.value} className={`kb-head${limit && n > limit ? " kb-over" : ""}`} data-testid={`colhead-${c.value}`}>
                <Group justify="space-between" wrap="nowrap" gap={4}>
                  <Badge color={c.color ?? "gray"} variant="light" className="badge-keep">{c.label}</Badge>
                  <Tooltip label={limit ? tx("WIP limit {limit}", { limit: limit }) : tx("{n} card(s)", { n: n })} disabled={!limit}>
                    <Text size="xs" c={limit && n > limit ? "red" : "dimmed"} fw={limit && n > limit ? 700 : undefined} data-testid={`count-${c.value}`}>{n}{limit ? ` / ${limit}` : ""}</Text>
                  </Tooltip>
                </Group>
              </div>
            );
          })}
          {laneGroups.map((l) => (
            <Lane key={l.value} lane={l} showHeader={!!lanes} collapsed={collapsed.has(l.value)} span={columns.length}
              onToggle={() => { const s = new Set(collapsed); if (s.has(l.value)) s.delete(l.value); else s.add(l.value); setCollapsed(s); }}
              count={lanes ? items.filter((i) => lanes.of(i) === l.value).length : items.length}>
              {columns.map((c) => {
                const cards = items.filter((i) => cols.of(i) === c.value && (!lanes || lanes.of(i) === l.value));
                const allowed = dragging ? validTarget(dragging, c.value) : true;
                return (
                  <Cell key={c.value} id={`${c.value}|${l.value}`} allowed={allowed} dragging={!!dragging} testId={lanes ? `cell-${c.value}-${l.value}` : `col-${c.value}`}>
                    {cards.map((i) => (
                      <DraggableCard key={i.id} item={i} disabled={!canEdit || busy === i.key} busy={busy === i.key} model={model}
                        showType={config.types.length !== 1 && config.columns_by !== "type" && config.swimlanes_by !== "type"}
                        showState={config.columns_by !== "state"} fields={cardFields} users={users} onOpen={() => setPreview(i.key)} />
                    ))}
                  </Cell>
                );
              })}
            </Lane>
          ))}
        </div>
      </ScrollArea>
      <DragOverlay>{dragging && <CardBody item={dragging} model={model} showType={false} showState={false} fields={[]} users={users} />}</DragOverlay>
      {pending && (
        <ActionPrompt opened onClose={() => { setPending(null); refresh(); }} title={`${pending.item.key}: ${pending.transition.label}`}
          meaning={pending.transition.signature ? tx("I sign \"{label}\" for {key}", { label: pending.transition.label, key: pending.item.key }) : undefined}
          signature={pending.transition.signature} commentRequired={pending.transition.comment_required} confirmLabel={pending.transition.label}
          onConfirm={async (r) => {
            try { await runTransition(pending.item, pending.transition, r); } catch (e) {
              notifications.show({ color: "red", title: tx("{key} not moved", { key: pending.item.key }), message: e instanceof ApiError ? e.message : String(e) });
            }
            setPending(null); refresh();
          }} />
      )}
      <Drawer opened={!!preview} onClose={() => setPreview(null)} position="right" size="lg" withCloseButton={false} padding="xs">
        {preview && <ItemPreview projectKey={projectKey} itemKey={preview} model={model} onClose={() => setPreview(null)} />}
      </Drawer>
    </DndContext>
  );
}

/** The plan each item is planned in directly (for release columns/swimlanes). */
function usePlanOf(projectKey: string, releases: Item[]): Record<string, string> {
  const keys = releases.map((r) => r.key);
  return useQuery<Record<string, string>>({
    queryKey: pk(projectKey, "plan-map", keys),
    queryFn: async () => {
      const details = await Promise.all(keys.map((k) => api.get<{ items: { key: string; plan: string }[] }>(`/projects/${projectKey}/plans/${k}`)));
      const m: Record<string, string> = {};
      for (const d of details) for (const it of d.items) m[it.key] = it.plan;
      return m;
    },
    enabled: keys.length > 0,
  }).data ?? EMPTY;
}

const EMPTY: Record<string, string> = {};

function Lane({ lane, showHeader, collapsed, onToggle, count, span, children }: {
  lane: Group_; showHeader: boolean; collapsed: boolean; onToggle: () => void; count: number; span: number; children: React.ReactNode;
}) {
  return (
    <>
      {showHeader && (
        <div className="kb-lane" style={{ gridColumn: `1 / span ${span}` }} data-testid={`lane-${lane.value}`}>
          <Group gap={4}>
            <ActionIcon size="xs" variant="subtle" color="gray" onClick={onToggle} aria-label={collapsed ? tx("Expand swimlane") : tx("Collapse swimlane")}>
              {collapsed ? <IconChevronRight size={14} /> : <IconChevronDown size={14} />}
            </ActionIcon>
            <Text size="sm" fw={600}>{lane.label}</Text>
            <Text size="xs" c="dimmed">{count}</Text>
          </Group>
        </div>
      )}
      {!collapsed && children}
    </>
  );
}

function Cell({ id, allowed, dragging, testId, children }: { id: string; allowed: boolean; dragging: boolean; testId: string; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id });  // invalid targets stay droppable: the drop explains why not
  return (
    <div ref={setNodeRef} className={`kb-cell${dragging ? (allowed ? " kb-ok" : " kb-no") : ""}${isOver && allowed ? " kb-over-cell" : ""}`} data-testid={testId}>
      <Stack gap={6}>{children}</Stack>
    </div>
  );
}

interface CardProps {
  item: Item; model: Model; showType: boolean; showState: boolean; users: UserRef[];
  fields: { key: string; def?: { label: string; type: string; options: { key: string; label: string; color?: string | null }[] } }[];
}

function DraggableCard(props: CardProps & { disabled: boolean; busy: boolean; onOpen: () => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: props.item.key, data: { item: props.item }, disabled: props.disabled });
  return (
    <div ref={setNodeRef} {...attributes} {...listeners} style={{ opacity: isDragging ? 0.35 : 1 }} data-testid={`card-${props.item.key}`}
      onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) props.onOpen(); }}>
      <CardBody {...props} />
    </div>
  );
}

function CardBody({ item, model, showType, showState, fields, users, busy }: CardProps & { busy?: boolean }) {
  const st = model.state(item.type_key, item.lifecycle.state);
  return (
    <Card withBorder padding="xs" className="kb-card" style={{ borderLeftColor: `var(--mantine-color-${(stateColor(st?.color, st?.category) ?? "gray").split(".")[0]}-6)` }}>
      <Group justify="space-between" gap={4} wrap="nowrap">
        <Text className="item-key" size="xs">{item.key}</Text>
        <Group gap={4} wrap="nowrap">
          {item.lifecycle.frozen && <IconLock size={12} color="var(--mantine-color-dimmed)" />}
          {busy && <Loader size={12} />}
          {item.owner && <Tooltip label={item.owner.display_name}><Avatar size={20} radius="xl" color="petrol">{initials(item.owner.display_name)}</Avatar></Tooltip>}
        </Group>
      </Group>
      <Text size="sm" lineClamp={2} mt={2}>{item.title}</Text>
      {(showType || showState || fields.some((f) => item.fields[f.key] != null)) && (
        <Group gap={4} mt={6}>
          {showType && <TypeBadge typeKey={item.type_key} />}
          {showState && st && <Badge size="xs" variant="light" color={stateColor(st.color, st.category)}>{st.label}</Badge>}
          {fields.map((f) => {
            const v = item.fields[f.key];
            if (v == null || v === "") return null;
            const o = f.def?.options?.find((x) => x.key === v);
            const label = f.def?.type === "user" ? users.find((u) => u.id === v)?.display_name ?? String(v) : o?.label ?? String(v);
            return <Badge key={f.key} size="xs" variant="outline" color={o?.color ?? "gray"} className="badge-keep">{f.def && f.def.type !== "enum" ? `${f.def.label}: ` : ""}{label}</Badge>;
          })}
        </Group>
      )}
    </Card>
  );
}

function initials(name: string): string {
  return name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}
