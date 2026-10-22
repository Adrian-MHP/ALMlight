// Helpers around the project's information model (item types, link types, workflows).

import type { FieldDef, Item, ItemTypeDef, LinkTypeDef, ProjectConfig, StateDef, WorkflowDef } from "@/api/types";

export const CATEGORY_LABELS: Record<string, string> = {
  requirement: "Requirements",
  architecture: "Architecture",
  verification: "Verification",
  change: "Change",
  document: "Documents",
  variability: "Variants",
  other: "Other",
};

export const CATEGORY_COLORS: Record<string, string> = {
  requirement: "indigo",
  architecture: "grape",
  verification: "teal",
  change: "orange",
  document: "blue",
  variability: "pink",
  other: "gray",
};

export class Model {
  constructor(public config: ProjectConfig) {}

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
