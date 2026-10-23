// Helpers around the project's information model (item types, link types, workflows).

import type { FieldDef, Item, ItemTypeDef, LinkTypeDef, ProjectConfig, StateDef, WorkflowDef } from "@/api/types";
import { locale, setModelTranslations, tm, tx } from "@/lib/i18n";

export const CATEGORY_LABELS: Record<string, string> = {
  requirement: tx("Requirements"),
  architecture: tx("Architecture"),
  verification: tx("Verification"),
  change: tx("Change"),
  document: tx("Documents"),
  variability: tx("Variants"),
  risk: tx("Risks"),
  planning: tx("Planning"),
  other: tx("Other"),
};

export const CATEGORY_COLORS: Record<string, string> = {
  requirement: "indigo",
  architecture: "grape",
  verification: "teal",
  change: "orange",
  document: "blue",
  variability: "pink",
  risk: "red",
  planning: "cyan",
  other: "gray",
};

/** A copy of the information model with its labels in the user's language (the model's own translations first). */
function localized(config: ProjectConfig): ProjectConfig {
  setModelTranslations(config.translations?.[locale()]);
  if (locale() === "en") return config;
  const l = (s: string | null | undefined) => (s ? tm(s) : s);
  return {
    ...config,
    item_types: config.item_types.map((t) => ({
      ...t, label: tm(t.label), description: l(t.description),
      fields: t.fields.map((f) => ({ ...f, label: tm(f.label), help: l(f.help), options: f.options?.map((o) => ({ ...o, label: tm(o.label) })) })),
    })),
    link_types: config.link_types.map((lt) => ({
      ...lt, label: tm(lt.label), reverse_label: tm(lt.reverse_label), description: l(lt.description),
      attributes: lt.attributes?.map((a) => ({ ...a, label: tm(a.label), help: l(a.help), options: a.options?.map((o) => ({ ...o, label: tm(o.label) })) })),
    })),
    workflows: config.workflows.map((w) => ({
      ...w, label: tm(w.label),
      states: w.states.map((st) => ({ ...st, label: tm(st.label) })),
      transitions: w.transitions.map((t) => ({ ...t, label: tm(t.label) })),
    })),
  };
}

export class Model {
  public config: ProjectConfig;

  constructor(config: ProjectConfig) {
    this.config = localized(config);
  }

  type(key: string): ItemTypeDef | undefined {
    return this.config.item_types.find((t) => t.key === key);
  }

  typeLabel(key: string): string {
    return this.type(key)?.label ?? key;
  }

  link(key: string): LinkTypeDef | undefined {
    return this.config.link_types.find((l) => l.key === key);
  }

  workflow(typeKey: string): WorkflowDef | undefined {
    const wf = this.type(typeKey)?.workflow;
    return wf ? this.config.workflows.find((w) => w.key === wf) : undefined;
  }

  state(typeKey: string, state: string | null): StateDef | undefined {
    return this.workflow(typeKey)?.states.find((s) => s.key === state);
  }

  field(typeKey: string, fieldKey: string): FieldDef | undefined {
    return this.type(typeKey)?.fields.find((f) => f.key === fieldKey);
  }

  typesIn(category: string): ItemTypeDef[] {
    return this.config.item_types.filter((t) => t.category === category);
  }

  get structuralLinks(): string[] {
    return this.config.link_types.filter((l) => l.structural).map((l) => l.key);
  }

  /** The risk item type if the information model has one (risk management). */
  get riskType(): ItemTypeDef | undefined {
    const k = this.config.semantics.risk_type;
    return k ? this.type(k) : undefined;
  }

  /** The release/milestone type if the information model supports planning. */
  get releaseType(): ItemTypeDef | undefined {
    const k = this.config.semantics.release_type;
    return k && this.link(this.config.semantics.planned_link) ? this.type(k) : undefined;
  }

  /** Item types that can be placed in a structure (BOM children). */
  get structureTargets(): string[] {
    return Array.from(new Set(this.config.link_types.filter((l) => l.structural).flatMap((l) => l.targets)));
  }

  get documentTypes(): ItemTypeDef[] {
    return this.config.item_types.filter((t) => t.document);
  }

  /** Grouped options for a type selector. */
  typeOptions(filter?: (t: ItemTypeDef) => boolean) {
    const groups: Record<string, { value: string; label: string }[]> = {};
    for (const t of this.config.item_types) {
      if (filter && !filter(t)) continue;
      (groups[CATEGORY_LABELS[t.category] ?? t.category] ??= []).push({ value: t.key, label: t.label });
    }
    return Object.entries(groups).map(([group, items]) => ({ group, items }));
  }

  /** Link types usable from (or to) an item of the given type, with direction. */
  linkOptions(typeKey: string) {
    const out: { value: string; label: string; linkType: string; direction: "outgoing" | "incoming"; otherTypes: string[] }[] = [];
    for (const lt of this.config.link_types) {
      const allTypes = this.config.item_types.map((t) => t.key);
      const expand = (list: string[]) => (list.includes("*") ? allTypes : list);
      if (lt.sources.includes("*") || lt.sources.includes(typeKey)) {
        out.push({ value: `${lt.key}:out`, label: lt.label, linkType: lt.key, direction: "outgoing", otherTypes: expand(lt.targets) });
      }
      if ((lt.targets.includes("*") || lt.targets.includes(typeKey)) && lt.key !== "relates_to") {
        out.push({ value: `${lt.key}:in`, label: lt.reverse_label, linkType: lt.key, direction: "incoming", otherTypes: expand(lt.sources) });
      }
    }
    return out;
  }

  isEditable(item: Item): boolean {
    return !item.lifecycle.frozen;
  }
}

export function stateColor(color: string | null | undefined, category?: string | null): string {
  if (color) return color === "dark" ? "gray.7" : color;
  switch (category) {
    case "released": return "green";
    case "review": return "yellow";
    case "obsolete": case "closed": return "gray";
    case "in_progress": return "blue";
    default: return "gray";
  }
}
