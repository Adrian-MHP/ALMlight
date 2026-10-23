import { useEffect, useMemo, useState } from "react";
import {
  Button, Card, Checkbox, Divider, Grid, Group, Modal, MultiSelect, NumberInput, ScrollArea, SegmentedControl, Select,
  Stack, Switch, Text, Textarea, TextInput, Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useFeatureModel, useWidgetPreview } from "@/api/hooks";
import type { ReportItemFilter, ReportWidget, WidgetType } from "@/api/types";
import { useProjectCtx } from "../ProjectLayout";
import { WidgetView } from "./WidgetView";
import { tx } from "@/lib/i18n";

export const WIDGET_TYPES: { value: WidgetType; label: string; group: string; description: string }[] = [
  { value: "kpi", label: tx("KPI number"), group: tx("Basic"), description: tx("Count or percentage of items, with an optional target") },
  { value: "chart", label: tx("Chart"), group: tx("Basic"), description: tx("Items grouped by state, type, owner or a field (bar, donut, pie)") },
  { value: "table", label: tx("Table"), group: tx("Basic"), description: tx("List of items with chosen columns") },
  { value: "trend", label: tx("Trend"), group: tx("Basic"), description: tx("Created / released / changed items over time") },
  { value: "markdown", label: tx("Text"), group: tx("Basic"), description: tx("Explanatory text (Markdown)") },
  { value: "coverage", label: tx("Coverage"), group: tx("Engineering"), description: tx("Refinement, allocation and verification of a requirement type") },
  { value: "matrix", label: tx("Traceability matrix"), group: tx("Engineering"), description: tx("Links between two item types") },
  { value: "maturity", label: tx("Maturity"), group: tx("Engineering"), description: tx("Specified / realised / verified / validated elements") },
  { value: "reuse", label: tx("Reuse rate per module"), group: tx("Platform KPIs"), description: tx("Products per module, reuse strategy") },
  { value: "change_lead_time", label: tx("Change lead time"), group: tx("Platform KPIs"), description: tx("Creation to decision/release of changes") },
  { value: "retest_effort", label: tx("Re-test effort per variant"), group: tx("Platform KPIs"), description: tx("Tests without a current passing result") },
  { value: "variant_ratio", label: tx("Module variants vs. variants"), group: tx("Platform KPIs"), description: tx("Modules needed per offered variant") },
];

const WIDTHS = [{ value: "3", label: "¼" }, { value: "4", label: "⅓" }, { value: "6", label: "½" }, { value: "8", label: "⅔" }, { value: "12", label: tx("Full") }];
const FILTERED: WidgetType[] = ["kpi", "chart", "table", "trend"];

export function newWidget(type: WidgetType): ReportWidget {
  const id = `w${Math.random().toString(36).slice(2, 8)}`;
  const label = WIDGET_TYPES.find((t) => t.value === type)?.label ?? type;
  const wide = ["table", "trend", "reuse", "change_lead_time", "retest_effort", "variant_ratio", "matrix"].includes(type);
  return { id, type, title: label, width: type === "kpi" ? 3 : wide ? 12 : 6, filter: {} };
}

export function WidgetEditor({ initial, onSave, onClose }: { initial: ReportWidget; onSave: (w: ReportWidget) => void; onClose: () => void }) {
  const { key, model } = useProjectCtx();
  const [w, setW] = useState<ReportWidget>(initial);
  useEffect(() => setW(initial), [initial]);
  const [debounced] = useDebouncedValue(w, 400);
  const preview = useWidgetPreview(key, debounced);
  const variants = useFeatureModel(key).data?.variants ?? [];
  const set = (patch: Partial<ReportWidget>) => setW((prev) => ({ ...prev, ...patch }));
  const setFilter = (patch: Partial<ReportItemFilter>) => setW((prev) => ({ ...prev, filter: { ...(prev.filter ?? {}), ...patch } }));

  const selectedTypes = w.filter?.types?.length ? w.filter.types : model.config.item_types.map((t) => t.key);
  const stateOptions = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of selectedTypes) for (const s of model.workflow(t)?.states ?? []) m.set(s.key, s.label);
    return [...m].map(([value, label]) => ({ value, label }));
  }, [selectedTypes, model]);
  const fieldDefs = useMemo(() => {
    const m = new Map<string, { key: string; label: string; type: string; options: { key: string; label: string }[] }>();
    for (const t of selectedTypes) for (const f of model.type(t)?.fields ?? []) if (!m.has(f.key)) m.set(f.key, f);
    return [...m.values()];
  }, [selectedTypes, model]);
  const groupOptions = [
    { value: "state", label: tx("State") }, { value: "type", label: tx("Item type") }, { value: "category", label: tx("Category") },
    { value: "owner", label: tx("Owner") },
    ...fieldDefs.filter((f) => ["enum", "boolean", "string", "multienum", "user"].includes(f.type)).map((f) => ({ value: `field:${f.key}`, label: f.label })),
  ];
  const columnOptions = [
    ...["key", "title", "type", "state", "version", "owner", "updated", "applicability"].map((c) => ({ value: c, label: c })),
    ...fieldDefs.filter((f) => f.type !== "text").map((f) => ({ value: `field:${f.key}`, label: f.label })),
  ];
  const typeOptions = model.typeOptions();
  const variantOptions = variants.map((v) => ({ value: v.key, label: `${v.key} — ${v.title}` }));
  const fieldEntries = Object.entries(w.filter?.fields ?? {});

  return (
    <Modal opened onClose={onClose} size="95%" title={WIDGET_TYPES.find((t) => t.value === w.type)?.label ?? tx("Widget")}>
      <Grid>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <ScrollArea.Autosize mah="70vh" offsetScrollbars>
            <Stack gap="sm">
              <TextInput label={tx("Title")} value={w.title ?? ""} onChange={(e) => set({ title: e.currentTarget.value })} data-testid="widget-title" />
              <div>
                <Text size="sm" fw={500} mb={4}>{tx("Width")}</Text>
                <SegmentedControl data={WIDTHS} value={String(w.width ?? 6)} onChange={(v) => set({ width: Number(v) })} />
              </div>
              {FILTERED.includes(w.type) && (
                <>
                  <Divider label={tx("Items")} labelPosition="left" />
                  <MultiSelect label={tx("Item types")} placeholder={tx("All types")} data={typeOptions} searchable value={w.filter?.types ?? []}
                    onChange={(v) => setFilter({ types: v })} data-testid="widget-types" />
                  <MultiSelect label={tx("States")} placeholder={tx("Any state")} data={stateOptions} value={w.filter?.states ?? []}
                    onChange={(v) => setFilter({ states: v })} />
                  {fieldEntries.map(([fk, fv], i) => (
                    <Group key={i} grow align="flex-end">
                      <Select label={tx("Field")} data={fieldDefs.map((f) => ({ value: f.key, label: f.label }))} value={fk}
                        onChange={(nk) => { const next = { ...(w.filter?.fields ?? {}) }; delete next[fk]; if (nk) next[nk] = fv; setFilter({ fields: next }); }} />
                      <FieldValueInput def={fieldDefs.find((f) => f.key === fk)} value={fv}
                        onChange={(nv) => setFilter({ fields: { ...(w.filter?.fields ?? {}), [fk]: nv } })} />
                      <Button variant="subtle" color="red" onClick={() => { const next = { ...(w.filter?.fields ?? {}) }; delete next[fk]; setFilter({ fields: next }); }}>{tx("Remove")}</Button>
                    </Group>
                  ))}
                  {fieldDefs.length > 0 && (
                    <Button size="xs" variant="subtle" onClick={() => {
                      const free = fieldDefs.find((f) => !(w.filter?.fields ?? {})[f.key]);
                      if (free) setFilter({ fields: { ...(w.filter?.fields ?? {}), [free.key]: free.options[0]?.key ?? "" } });
                    }}>{tx("+ Field condition")}</Button>
                  )}
                  <TextInput label={tx("Text search")} value={w.filter?.q ?? ""} onChange={(e) => setFilter({ q: e.currentTarget.value || null })} />
                  <Group grow>
                    <Select label={tx("Only items of variant")} clearable data={variantOptions} value={w.filter?.variant ?? null} onChange={(v) => setFilter({ variant: v })} />
                    <Checkbox mt="lg" label={tx("Only with suspect links")} checked={!!w.filter?.suspect} onChange={(e) => setFilter({ suspect: e.currentTarget.checked || null })} />
                  </Group>
                </>
              )}
              {w.type === "kpi" && (
                <>
                  <Divider label={tx("Metric")} labelPosition="left" />
                  <SegmentedControl value={w.metric ?? "count"} onChange={(v) => set({ metric: v as "count" | "percent" })}
                    data={[{ value: "count", label: tx("Count") }, { value: "percent", label: tx("Percentage") }]} data-testid="widget-metric" />
                  {w.metric === "percent" && (
                    <MultiSelect label={tx("… of which in state")} data={stateOptions} value={w.percent_of?.states ?? []}
                      onChange={(v) => set({ percent_of: { ...(w.percent_of ?? {}), states: v } })} data-testid="widget-percent-states" />
                  )}
                  <NumberInput label={tx("Target (optional)")} value={w.target ?? ""} onChange={(v) => set({ target: v === "" ? null : Number(v) })} />
                </>
              )}
              {w.type === "chart" && (
                <>
                  <Divider label={tx("Chart")} labelPosition="left" />
                  <Select label={tx("Group by")} data={groupOptions} value={w.group_by ?? "state"} onChange={(v) => set({ group_by: v ?? "state" })} allowDeselect={false} data-testid="widget-group" />
                  <Select label={tx("Split bars by (optional)")} clearable data={groupOptions} value={w.stack_by ?? null} onChange={(v) => set({ stack_by: v })} />
                  <SegmentedControl value={w.chart ?? "bar"} onChange={(v) => set({ chart: v as ReportWidget["chart"] })}
                    data={[{ value: "bar", label: tx("Bars") }, { value: "horizontal", label: tx("Horizontal") }, { value: "donut", label: tx("Donut") }, { value: "pie", label: tx("Pie") }]} />
                </>
              )}
              {w.type === "table" && (
                <>
                  <Divider label={tx("Table")} labelPosition="left" />
                  <MultiSelect label={tx("Columns")} data={columnOptions} value={w.columns ?? ["key", "title", "state"]} onChange={(v) => set({ columns: v })} searchable />
                  <Group grow>
                    <Select label={tx("Sort")} data={[{ value: "key", label: tx("Key") }, { value: "-updated", label: tx("Recently updated") }, { value: "title", label: tx("Title") }, { value: "state", label: tx("State") }]}
                      value={w.sort ?? "key"} onChange={(v) => set({ sort: v ?? "key" })} allowDeselect={false} />
                    <NumberInput label={tx("Rows")} min={1} max={500} value={w.limit ?? 50} onChange={(v) => set({ limit: Number(v) || 50 })} />
                  </Group>
                </>
              )}
              {w.type === "trend" && (
                <>
                  <Divider label={tx("Trend")} labelPosition="left" />
                  <MultiSelect label={tx("Series")} data={[{ value: "created", label: tx("Created") }, { value: "released", label: tx("Released / approved") }, { value: "changed", label: tx("Changed (new versions)") }]}
                    value={w.series ?? ["created", "released"]} onChange={(v) => set({ series: v as ReportWidget["series"] })} />
                  <Group grow>
                    <Select label={tx("Interval")} data={[{ value: "week", label: tx("Weeks") }, { value: "month", label: tx("Months") }]} value={w.interval ?? "week"}
                      onChange={(v) => set({ interval: (v ?? "week") as "week" | "month" })} allowDeselect={false} />
                    <NumberInput label={tx("Periods")} min={2} max={104} value={w.periods ?? 12} onChange={(v) => set({ periods: Number(v) || 12 })} />
                  </Group>
                  <Switch label={tx("Cumulative (burn-up)")} checked={!!w.cumulative} onChange={(e) => set({ cumulative: e.currentTarget.checked })} />
                </>
              )}
              {w.type === "coverage" && (
                <Select label={tx("Requirement type")} data={model.typesIn("requirement").map((t) => ({ value: t.key, label: t.label }))}
                  value={w.coverage_type ?? null} onChange={(v) => set({ coverage_type: v })} />
              )}
              {(w.type === "coverage" || w.type === "maturity" || w.type === "retest_effort") && (
                <Select label={w.type === "retest_effort" ? tx("Only variant (optional)") : tx("Verification results of variant (optional)")} clearable
                  data={variantOptions} value={w.variant ?? null} onChange={(v) => set({ variant: v })} />
              )}
              {w.type === "matrix" && (
                <Group grow>
                  <Select label={tx("Rows")} data={typeOptions} value={w.rows ?? null} onChange={(v) => set({ rows: v })} searchable />
                  <Select label={tx("Columns")} data={typeOptions} value={w.cols ?? null} onChange={(v) => set({ cols: v })} searchable />
                </Group>
              )}
              {w.type === "change_lead_time" && (
                <>
                  <MultiSelect label={tx("Change types")} placeholder={tx("All change types")} data={model.typesIn("change").map((t) => ({ value: t.key, label: t.label }))}
                    value={w.change_types ?? []} onChange={(v) => set({ change_types: v })} />
                  <Select label={tx("Trend interval")} data={[{ value: "week", label: tx("Weeks") }, { value: "month", label: tx("Months") }]} value={w.interval ?? "month"}
                    onChange={(v) => set({ interval: (v ?? "month") as "week" | "month" })} allowDeselect={false} />
                </>
              )}
              {w.type === "markdown" && (
                <Textarea label={tx("Text (Markdown)")} autosize minRows={6} value={w.text ?? ""} onChange={(e) => set({ text: e.currentTarget.value })} />
              )}
            </Stack>
          </ScrollArea.Autosize>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Text size="xs" c="dimmed" mb={4}>{tx("Live preview")}</Text>
          <Card withBorder data-testid="widget-preview">
            <Title order={6} mb="sm">{w.title}</Title>
            <WidgetView widget={debounced} data={preview.data} />
          </Card>
        </Grid.Col>
      </Grid>
      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
        <Button onClick={() => onSave(w)} data-testid="widget-save">{tx("Apply")}</Button>
      </Group>
    </Modal>
  );
}

function FieldValueInput({ def, value, onChange }: { def?: { type: string; options: { key: string; label: string }[] }; value: string; onChange: (v: string) => void }) {
  if (def?.type === "enum" || def?.type === "multienum") {
    return <Select label={tx("Value")} data={def.options.map((o) => ({ value: o.key, label: o.label }))} value={value || null} onChange={(v) => onChange(v ?? "")} />;
  }
  if (def?.type === "boolean") {
    return <Select label={tx("Value")} data={[{ value: "true", label: tx("Yes") }, { value: "false", label: tx("No") }]} value={value || null} onChange={(v) => onChange(v ?? "")} />;
  }
  return <TextInput label={tx("Value")} value={value} onChange={(e) => onChange(e.currentTarget.value)} />;
}
