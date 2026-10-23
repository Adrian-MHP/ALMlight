import { useMemo, useState } from "react";
import { ActionIcon, Badge, Card, Grid, Group, SegmentedControl, Select, Stack, Text } from "@mantine/core";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";
import { useSearchParams } from "react-router-dom";
import { useFeatureModel, useItems, useMaturity, useTree } from "@/api/hooks";
import type { MaturityRow, TreeNode } from "@/api/types";
import { ItemLink, MaturityDot, StateBadge } from "@/components/badges";
import { PageHeader } from "@/components/PageHeader";
import { useProjectCtx } from "./ProjectLayout";
import { BomView } from "./BomView";
import { api } from "@/api/client";
import { useQuery } from "@tanstack/react-query";

const REUSE_COLORS: Record<string, string> = { new: "red", modified: "orange", reused: "green", standard: "teal", purchased: "blue" };

/** Product / system structure (decomposition) with reuse strategy, maturity and a variant filter. */
export function StructurePage() {
  const { key, model } = useProjectCtx();
  const [params, setParams] = useSearchParams();
  const elementTypes = model.config.semantics.element_types.filter((t) => model.type(t));
  const roots = useItems(key, { type: elementTypes, limit: 200, fields: { level: "product" } }).data?.items ?? [];
  const root = params.get("root") ?? roots[0]?.key ?? null;
  const features = useFeatureModel(key).data;
  const [variant, setVariant] = useState<string | null>(null);
  const view = params.get("view") ?? "tree";
  const setView = (v: string) => { const p = new URLSearchParams(params); p.set("view", v); if (root) p.set("root", root); setParams(p); };
  return (
    <>
      <PageHeader title="Structure" subtitle="System decomposition (product › system › subsystem › module › component) with reuse and maturity — or as a bill of materials with quantities and effectivity" />
      <Grid>
        <Grid.Col span={{ base: 12, md: 3 }}>
          <Card withBorder>
            <Stack>
              <SegmentedControl value={view} onChange={setView} fullWidth data-testid="structure-view"
                data={[{ value: "tree", label: "Structure" }, { value: "bom", label: "BOM" }]} />
              <Select label="Root element" value={root} onChange={(v) => v && setParams({ root: v, view })}
                data={roots.map((r) => ({ value: r.key, label: `${r.key} — ${r.title}` }))} searchable data-testid="structure-root" />
              <Select label="Variant filter" placeholder="150% — all variants" clearable value={variant} onChange={setVariant}
                data={(features?.variants ?? []).map((v) => ({ value: v.key, label: `${v.key} — ${v.title}` }))} data-testid="structure-variant" />
              <Stack gap={4}>
                <Text size="xs" c="dimmed">Maturity (per element)</Text>
                <Text size="xs">● specified · realised · verified · validated</Text>
                <Text size="xs" c="dimmed">Reuse strategy</Text>
                <Group gap={4}>{Object.entries(REUSE_COLORS).map(([k, c]) => <Badge key={k} size="xs" color={c} variant="light">{k}</Badge>)}</Group>
              </Stack>
            </Stack>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 9 }}>
          <Card withBorder>
            {!root ? <Text c="dimmed">No product-level element yet. Create a system element with level “product”.</Text>
              : view === "bom" ? <BomView rootKey={root} /> : <StructureTree rootKey={root} variant={variant} />}
          </Card>
        </Grid.Col>
      </Grid>
    </>
  );
}

export function StructureTree({ rootKey, variant }: { rootKey: string; variant?: string | null }) {
  const { key } = useProjectCtx();
  const tree = useTree(key, rootKey).data;
  const maturity = useMaturity(key, variant).data ?? [];
  const resolved = useQuery<{ excluded: { key: string }[]; excluded_link_ids: string[] }>({
    queryKey: ["p", key, "resolve-variant", variant],
    queryFn: () => api.get(`/projects/${key}/variants/${variant}/resolve`),
    enabled: !!variant,
  }).data;
  const byKey = useMemo(() => new Map(maturity.map((m) => [m.key, m])), [maturity]);
  const hidden = useMemo(() => new Set([...(resolved?.excluded.map((e) => e.key) ?? [])]), [resolved]);
  const hiddenLinks = useMemo(() => new Set(resolved?.excluded_link_ids ?? []), [resolved]);
  if (!tree) return null;
  return <Node node={tree} depth={0} maturity={byKey} hidden={variant ? hidden : new Set()} hiddenLinks={variant ? hiddenLinks : new Set()} />;
}

function Node({ node, depth, maturity, hidden, hiddenLinks }: {
  node: TreeNode; depth: number; maturity: Map<string, MaturityRow>; hidden: Set<string>; hiddenLinks: Set<string>;
}) {
  const [open, setOpen] = useState(depth < 3);
  const m = maturity.get(node.key);
  const level = node.fields.level as string | undefined;
  const reuse = node.fields.reuse_strategy as string | undefined;
  const kids = node.children.filter((c) => !hidden.has(c.key) && !(c.link && hiddenLinks.has(c.link.id)));
  return (
    <div>
      <Group className="tree-row" gap="xs" wrap="nowrap" style={{ paddingLeft: depth * 20 }} data-testid={`tree-${node.key}`}>
        {kids.length ? (
          <ActionIcon size="sm" variant="subtle" onClick={() => setOpen(!open)}>{open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}</ActionIcon>
        ) : <span style={{ width: 28 }} />}
        <ItemLink item={node} />
        <Text size="sm" truncate style={{ flex: 1 }}>{node.title}</Text>
        {node.link?.attributes?.quantity ? <Text size="xs" c="dimmed">× {String(node.link.attributes.quantity)}</Text> : null}
        {node.applicability && <Badge size="xs" color="pink" variant="light" className="mono" style={{ textTransform: "none" }}>{node.applicability}</Badge>}
        {level && <Badge size="xs" variant="outline" color="gray">{level}</Badge>}
        {reuse && <Badge size="xs" variant="light" color={REUSE_COLORS[reuse] ?? "gray"}>{reuse}</Badge>}
        <StateBadge item={node} size="xs" />
        {m && (
          <Group gap={2} wrap="nowrap">
            <MaturityDot value={m.specified} label="Specified" />
            <MaturityDot value={m.realised} label="Realised" />
            <MaturityDot value={m.verified} label="Verified" />
            <MaturityDot value={m.validated} label="Validated" />
          </Group>
        )}
      </Group>
      {open && kids.map((c) => <Node key={`${c.id}-${c.link?.id}`} node={c} depth={depth + 1} maturity={maturity} hidden={hidden} hiddenLinks={hiddenLinks} />)}
    </div>
  );
}
