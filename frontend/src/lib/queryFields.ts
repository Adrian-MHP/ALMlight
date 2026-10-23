// Fields offered by the query builder — the same names the server's query engine understands.

import type { CondGroup, Condition, FieldDef, QNode, UserRef } from "@/api/types";
import type { Model } from "./model";
import { tx } from "@/lib/i18n";

export type QKind = "enum" | "user" | "text" | "number" | "date" | "bool" | "link" | "release" | "multi";

export interface QOption { value: string; label: string }

export interface QField {
  id: string;
  label: string;
  kind: QKind;
  group: string;
  options?: QOption[];
  /** free values allowed besides the options (keys, revisions, tags) */
  free?: boolean;
  def?: FieldDef;
}

const CATEGORY_OPTIONS: QOption[] = [
  { value: "draft", label: tx("Draft") }, { value: "review", label: tx("In review") }, { value: "released", label: tx("Released") },
  { value: "open", label: tx("Open") }, { value: "in_progress", label: tx("In progress") }, { value: "closed", label: tx("Closed") },
  { value: "obsolete", label: tx("Obsolete") },
];

const KIND_OF: Record<string, QKind> = {
  enum: "enum", user: "user", string: "text", text: "text", url: "text", integer: "number", number: "number",
  date: "date", boolean: "bool", multienum: "multi", tags: "multi",
};

/** The catalog of query fields for a project; custom fields are limited to the selected types when given. */
export function queryFields(model: Model, opts: { users: UserRef[]; releases: QOption[]; types?: string[] }): QField[] {
  const types = opts.types?.length ? model.config.item_types.filter((t) => opts.types!.includes(t.key)) : model.config.item_types;
  const stateMap = new Map<string, string>();
  for (const t of types) for (const s of model.workflow(t.key)?.states ?? []) if (!stateMap.has(s.key)) stateMap.set(s.key, s.label);
  const userOptions: QOption[] = [{ value: "me", label: tx("Me") }, { value: "none", label: tx("Nobody") },
    ...opts.users.map((u) => ({ value: u.username, label: u.display_name }))];
  const out: QField[] = [
    { id: "type", label: tx("Type"), kind: "enum", group: tx("Common"), options: model.config.item_types.map((t) => ({ value: t.key, label: t.label })) },
    { id: "state", label: tx("Status"), kind: "enum", group: tx("Common"), options: [...stateMap].map(([value, label]) => ({ value, label })) },
    { id: "category", label: tx("Status category"), kind: "enum", group: tx("Common"), options: CATEGORY_OPTIONS },
    { id: "owner", label: tx("Owner"), kind: "user", group: tx("Common"), options: userOptions },
    { id: "title", label: tx("Title"), kind: "text", group: tx("Common") },
    { id: "text", label: tx("Text"), kind: "text", group: tx("Common") },
    { id: "key", label: tx("Key"), kind: "enum", group: tx("Common"), free: true, options: [] },
    { id: "created", label: tx("Created"), kind: "date", group: tx("Dates & people") },
    { id: "updated", label: tx("Updated"), kind: "date", group: tx("Dates & people") },
    { id: "author", label: tx("Created by"), kind: "user", group: tx("Dates & people"), options: userOptions },
    { id: "revision", label: tx("Revision"), kind: "enum", group: tx("Lifecycle"), free: true, options: "ABCDEF".split("").map((r) => ({ value: r, label: r })) },
    { id: "released", label: tx("Has a released version"), kind: "bool", group: tx("Lifecycle") },
    { id: "frozen", label: tx("Frozen"), kind: "bool", group: tx("Lifecycle") },
    { id: "applicability", label: tx("Applicability"), kind: "text", group: tx("Lifecycle") },
    { id: "suspect", label: tx("Has suspect links"), kind: "bool", group: tx("Flags") },
    { id: "watched", label: tx("Watched by me"), kind: "bool", group: tx("Flags") },
    { id: "checkedout", label: tx("Has checked-out files"), kind: "bool", group: tx("Flags") },
    { id: "attachments", label: tx("Has files"), kind: "bool", group: tx("Flags") },
  ];
  if (model.releaseType) {
    out.push({ id: "release", label: tx("Planned in"), kind: "release", group: tx("Planning"),
      options: [{ value: "none", label: tx("Not planned") }, ...opts.releases] });
  }
  for (const lt of model.config.link_types) {
    if (lt.structural) continue;
    out.push({ id: `link.${lt.key}.out`, label: cap(lt.label), kind: "link", group: tx("Traceability") });
    out.push({ id: `link.${lt.key}.in`, label: cap(lt.reverse_label), kind: "link", group: tx("Traceability") });
  }
  const seen = new Set<string>();
  for (const t of types) {
    for (const f of t.fields) {
      if (f.type === "steps" || seen.has(f.key)) continue;
      seen.add(f.key);
      const kind = KIND_OF[f.type] ?? "text";
      const options = kind === "user" ? userOptions
        : f.options?.length ? f.options.map((o) => ({ value: o.key, label: o.label })) : undefined;
      out.push({ id: `field.${f.key}`, label: f.label, kind, group: opts.types?.length ? tx("Fields") : tx("Fields (all types)"),
        options, free: kind === "multi" && !f.options?.length, def: f });
    }
  }
  return out;
}

function cap(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

export function defaultOp(kind: QKind): Condition["op"] {
  return kind === "text" ? "contains" : kind === "number" || kind === "date" ? "between" : kind === "bool" ? "is"
    : kind === "link" ? "exists" : "in";
}

/** Short human-readable text for a chip, e.g. "Status: Draft, In review" or "Verified by: none". */
export function conditionLabel(c: Condition, f: QField | undefined): string {
  const name = f?.label ?? c.field;
  const lbl = (v: unknown) => f?.options?.find((o) => o.value === String(v))?.label ?? String(v);
  let value: string;
  if (c.op === "exists") {
    const has = c.values[0] !== false;
    const positive = c.not ? !has : has;
    return f?.kind === "link" ? `${name}: ${positive ? tx("any") : tx("none")}` : `${name}: ${positive ? tx("has a value") : tx("empty")}`;
  } else if (c.op === "between") {
    const [a, b] = c.values as (string | number | null)[];
    value = a != null && a === b ? String(a) : `${a ?? "…"} → ${b ?? "…"}`;
  } else if (c.op === "is") {
    value = String(c.values[0]) === "true" || c.values[0] === true ? "yes" : "no";
  } else {
    const vals = c.values.map(lbl);
    value = vals.length > 3 ? `${vals.slice(0, 2).join(", ")} +${vals.length - 2}` : vals.join(", ") || "–";
  }
  return `${c.not ? "NOT " : ""}${name}: ${value}`;
}

export function isGroup(n: QNode): n is CondGroup {
  return "or" in n || "and" in n;
}

export function groupKind(g: CondGroup): "or" | "and" {
  return g.or ? "or" : "and";
}

export function children(g: CondGroup): QNode[] {
  return g.or ?? g.and ?? [];
}

export function makeGroup(kind: "or" | "and", nodes: QNode[], not = false): CondGroup {
  return kind === "or" ? { or: nodes, ...(not ? { not } : {}) } : { and: nodes, ...(not ? { not } : {}) };
}

/** A group reduced to one member becomes that member; the group's negation moves onto it. */
export function collapse(g: CondGroup): QNode {
  const kids = children(g);
  if (kids.length !== 1) return g;
  const only = kids[0];
  return g.not ? { ...only, not: !only.not } : only;
}

/** Top-level leaf conditions (implicitly AND-combined) — what pages use to infer types or plans. */
export function topLeaves(nodes: QNode[]): Condition[] {
  return nodes.filter((n): n is Condition => !isGroup(n));
}

/** Chip text for a condition or a group, e.g. "(Priority: Must OR Owner: Nobody)". */
export function nodeLabel(n: QNode, byId: Map<string, QField>, nested = false): string {
  if (!isGroup(n)) return conditionLabel(n, byId.get(n.field));
  const kids = children(n);
  const sep = groupKind(n) === "or" ? " OR " : " AND ";
  const parts = kids.map((k) => nodeLabel(k, byId, true));
  const body = parts.length > 3 ? `${parts.slice(0, 2).join(sep)}${sep}+${parts.length - 2}` : parts.join(sep);
  const wrapped = n.not || nested || groupKind(n) === "or" ? `(${body})` : body;
  return `${n.not ? "NOT " : ""}${wrapped}`;
}

/** Older saved views stored separate keys; express them as conditions. */
export function legacyToConditions(q: Record<string, unknown>): QNode[] {
  const out: QNode[] = [];
  const type = q.type as string[] | undefined;
  if (type?.length) out.push({ field: "type", op: "in", values: type });
  const state = q.state as string[] | undefined;
  if (state?.length) out.push({ field: "state", op: "in", values: state });
  if (q.suspect) out.push({ field: "suspect", op: "is", values: [true] });
  if (q.planned_in) out.push({ field: "release", op: "in", values: [q.planned_in] });
  if (q.link_type) {
    out.push({ field: `link.${q.link_type}.${q.link_dir === "in" ? "in" : "out"}`, op: "exists", values: [true], not: q.link_exists === false });
  }
  return [...out, ...((q.conditions as QNode[] | undefined) ?? [])];
}
