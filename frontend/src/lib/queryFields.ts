// Fields offered by the query builder — the same names the server's query engine understands.

import type { Condition, FieldDef, UserRef } from "@/api/types";
import type { Model } from "./model";

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
  { value: "draft", label: "Draft" }, { value: "review", label: "In review" }, { value: "released", label: "Released" },
  { value: "open", label: "Open" }, { value: "in_progress", label: "In progress" }, { value: "closed", label: "Closed" },
  { value: "obsolete", label: "Obsolete" },
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
  const userOptions: QOption[] = [{ value: "me", label: "Me" }, { value: "none", label: "Nobody" },
    ...opts.users.map((u) => ({ value: u.username, label: u.display_name }))];
  const out: QField[] = [
    { id: "type", label: "Type", kind: "enum", group: "Common", options: model.config.item_types.map((t) => ({ value: t.key, label: t.label })) },
    { id: "state", label: "Status", kind: "enum", group: "Common", options: [...stateMap].map(([value, label]) => ({ value, label })) },
    { id: "category", label: "Status category", kind: "enum", group: "Common", options: CATEGORY_OPTIONS },
    { id: "owner", label: "Owner", kind: "user", group: "Common", options: userOptions },
    { id: "title", label: "Title", kind: "text", group: "Common" },
    { id: "text", label: "Text", kind: "text", group: "Common" },
    { id: "key", label: "Key", kind: "enum", group: "Common", free: true, options: [] },
    { id: "created", label: "Created", kind: "date", group: "Dates & people" },
    { id: "updated", label: "Updated", kind: "date", group: "Dates & people" },
    { id: "author", label: "Created by", kind: "user", group: "Dates & people", options: userOptions },
    { id: "revision", label: "Revision", kind: "enum", group: "Lifecycle", free: true, options: "ABCDEF".split("").map((r) => ({ value: r, label: r })) },
    { id: "released", label: "Has a released version", kind: "bool", group: "Lifecycle" },
    { id: "frozen", label: "Frozen", kind: "bool", group: "Lifecycle" },
    { id: "applicability", label: "Applicability", kind: "text", group: "Lifecycle" },
    { id: "suspect", label: "Has suspect links", kind: "bool", group: "Flags" },
    { id: "watched", label: "Watched by me", kind: "bool", group: "Flags" },
    { id: "checkedout", label: "Has checked-out files", kind: "bool", group: "Flags" },
    { id: "attachments", label: "Has files", kind: "bool", group: "Flags" },
  ];
  if (model.releaseType) {
    out.push({ id: "release", label: "Planned in", kind: "release", group: "Planning",
      options: [{ value: "none", label: "Not planned" }, ...opts.releases] });
  }
  for (const lt of model.config.link_types) {
    if (lt.structural) continue;
    out.push({ id: `link.${lt.key}.out`, label: cap(lt.label), kind: "link", group: "Traceability" });
    out.push({ id: `link.${lt.key}.in`, label: cap(lt.reverse_label), kind: "link", group: "Traceability" });
  }
  const seen = new Set<string>();
  for (const t of types) {
    for (const f of t.fields) {
      if (f.type === "steps" || seen.has(f.key)) continue;
      seen.add(f.key);
      const kind = KIND_OF[f.type] ?? "text";
      const options = kind === "user" ? userOptions
        : f.options?.length ? f.options.map((o) => ({ value: o.key, label: o.label })) : undefined;
      out.push({ id: `field.${f.key}`, label: f.label, kind, group: opts.types?.length ? "Fields" : "Fields (all types)",
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
    return f?.kind === "link" ? `${name}: ${positive ? "any" : "none"}` : `${name}: ${positive ? "has a value" : "empty"}`;
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

/** Older saved views stored separate keys; express them as conditions. */
export function legacyToConditions(q: Record<string, unknown>): Condition[] {
  const out: Condition[] = [];
  const type = q.type as string[] | undefined;
  if (type?.length) out.push({ field: "type", op: "in", values: type });
  const state = q.state as string[] | undefined;
  if (state?.length) out.push({ field: "state", op: "in", values: state });
  if (q.suspect) out.push({ field: "suspect", op: "is", values: [true] });
  if (q.planned_in) out.push({ field: "release", op: "in", values: [q.planned_in] });
  if (q.link_type) {
    out.push({ field: `link.${q.link_type}.${q.link_dir === "in" ? "in" : "out"}`, op: "exists", values: [true], not: q.link_exists === false });
  }
  return [...out, ...((q.conditions as Condition[] | undefined) ?? [])];
}
