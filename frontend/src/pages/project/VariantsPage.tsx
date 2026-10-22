import { useMemo, useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, Grid, Group, Radio, Stack, Table, Text, Title } from "@mantine/core";
import { IconAlertTriangle, IconCircleCheck } from "@tabler/icons-react";
import { useFeatureModel, useResolve } from "@/api/hooks";
import type { FeatureNode } from "@/api/types";
import { ItemLink, StateBadge } from "@/components/badges";
import { PageHeader } from "@/components/PageHeader";
import { useProjectCtx } from "./ProjectLayout";

/** Feature model, product variants and an interactive configurator (150% → 100% view). */
export function VariantsPage() {
  const { key, model } = useProjectCtx();
  const fm = useFeatureModel(key).data;
  const [selection, setSelection] = useState<string[] | null>(null);
  const resolved = useResolve(key, selection);
  const selected = useMemo(() => new Set(selection ?? []), [selection]);

  function toggle(node: FeatureNode, parent: FeatureNode | null, on: boolean) {
    const next = new Set(selected);
    if (on) {
      next.add(node.code);
      if (parent?.group === "alternative") parent.children.forEach((c) => c.code !== node.code && removeTree(c, next));
    } else {
      removeTree(node, next);
    }
    setSelection([...next]);
  }

  return (
    <>
      <PageHeader title="Variants" subtitle="Feature model with constraints, product variants and a configurator that filters the 150% model" />
      {fm && fm.unknown_codes.length > 0 && (
        <Alert color="yellow" mb="md" icon={<IconAlertTriangle size={16} />} title="Applicability expressions reference unknown features">
          {fm.unknown_codes.map((u) => `${u.key}: ${u.missing.join(", ")}`).join(" · ")}
        </Alert>
      )}
      <Grid>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Card withBorder mb="md">
            <Title order={5} mb="xs">Feature model</Title>
            {fm?.roots.length === 0 && <Text c="dimmed" size="sm">No features yet. Create items of the feature type and arrange them in a tree.</Text>}
            {fm?.roots.map((r) => <FeatureRow key={r.code} node={r} parent={null} depth={0} selected={selected} onToggle={toggle} />)}
            {fm && (fm.requires.length > 0 || fm.excludes.length > 0) && (
              <Stack gap={2} mt="sm">
                <Text size="xs" c="dimmed">Constraints</Text>
                {fm.requires.map((c, i) => <Text size="xs" key={`r${i}`} className="mono">{c.from} requires {c.to}</Text>)}
                {fm.excludes.map((c, i) => <Text size="xs" key={`e${i}`} className="mono">{c.from} excludes {c.to}</Text>)}
              </Stack>
            )}
          </Card>
          <Card withBorder>
            <Title order={5} mb="xs">Defined variants</Title>
            <Table>
              <Table.Tbody>
                {fm?.variants.map((v) => (
                  <Table.Tr key={v.key}>
                    <Table.Td><ItemLink item={v} withTitle /></Table.Td>
                    <Table.Td>{v.errors.length ? <Badge color="red" size="sm">{v.errors.length} issue(s)</Badge> : <Badge color="green" size="sm" variant="light">valid</Badge>}</Table.Td>
                    <Table.Td><Button size="xs" variant="subtle" onClick={() => setSelection(v.selection)} data-testid={`load-${v.key}`}>Load</Button></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Card withBorder data-testid="configurator">
            <Group justify="space-between" mb="xs">
              <Title order={5}>Configuration</Title>
              {selection && <Button size="xs" variant="subtle" onClick={() => setSelection(null)}>Clear</Button>}
            </Group>
            {!selection && <Text c="dimmed" size="sm">Select features on the left or load a variant to see which items apply.</Text>}
            {selection && resolved.data && (
              <Stack>
                <Group gap={4}>{[...selected].sort().map((c) => <Badge key={c} variant="light" className="mono" style={{ textTransform: "none" }}>{c}</Badge>)}</Group>
                {resolved.data.errors.length ? (
                  <Alert color="red" icon={<IconAlertTriangle size={16} />} title="Invalid configuration" data-testid="config-errors">
                    {resolved.data.errors.map((e) => <Text key={e} size="sm">{e}</Text>)}
                  </Alert>
                ) : (
                  <Alert color="green" icon={<IconCircleCheck size={16} />} data-testid="config-valid">Valid configuration</Alert>
                )}
                <Table>
                  <Table.Thead><Table.Tr><Table.Th>Type</Table.Th><Table.Th ta="right">Included</Table.Th><Table.Th ta="right">Excluded</Table.Th></Table.Tr></Table.Thead>
                  <Table.Tbody>
                    {Object.entries(resolved.data.counts).map(([t, c]) => (
                      <Table.Tr key={t}><Table.Td>{model.typeLabel(t)}</Table.Td><Table.Td ta="right">{c.included}</Table.Td><Table.Td ta="right">{c.excluded}</Table.Td></Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
                <Text size="sm" fw={600}>Variant-specific items included</Text>
                <Stack gap={2}>
                  {resolved.data.included.filter((i) => i.applicability).map((i) => (
                    <Group key={i.id} gap="xs"><ItemLink item={i} withTitle /><StateBadge item={i} size="xs" />
                      <Text size="xs" className="mono" c="pink">{i.applicability}</Text></Group>
                  ))}
                </Stack>
                <Text size="sm" fw={600}>Excluded items</Text>
                <Stack gap={2}>
                  {resolved.data.excluded.map((i) => (
                    <Group key={i.id} gap="xs" opacity={0.7}><ItemLink item={i} withTitle /><Text size="xs" className="mono" c="pink">{i.applicability}</Text></Group>
                  ))}
                </Stack>
              </Stack>
            )}
          </Card>
        </Grid.Col>
      </Grid>
    </>
  );
}

function removeTree(node: FeatureNode, set: Set<string>) {
  set.delete(node.code);
  node.children.forEach((c) => removeTree(c, set));
}

function FeatureRow({ node, parent, depth, selected, onToggle }: {
  node: FeatureNode; parent: FeatureNode | null; depth: number; selected: Set<string>;
  onToggle: (n: FeatureNode, p: FeatureNode | null, on: boolean) => void;
}) {
  const checked = selected.has(node.code);
  const label = (
    <Group gap={6} wrap="nowrap">
      <Text size="sm" className="mono" fw={600}>{node.code}</Text>
      <Text size="sm">{node.title}</Text>
      {node.kind === "mandatory" && <Badge size="xs" variant="outline">mandatory</Badge>}
      {node.group !== "none" && <Badge size="xs" color="grape" variant="light">{node.group === "alternative" ? "choose one" : "choose ≥1"}</Badge>}
      {node.obsolete && <Badge size="xs" color="gray">obsolete</Badge>}
    </Group>
  );
  return (
    <div style={{ marginLeft: depth * 18, marginTop: 4 }}>
      {parent?.group === "alternative" ? (
        <Radio label={label} checked={checked} onChange={() => onToggle(node, parent, true)} disabled={node.obsolete} data-testid={`feature-${node.code}`} />
      ) : (
        <Checkbox label={label} checked={checked} onChange={(e) => onToggle(node, parent, e.currentTarget.checked)} disabled={node.obsolete} data-testid={`feature-${node.code}`} />
      )}
      {node.children.map((c) => <FeatureRow key={c.code} node={c} parent={node} depth={depth + 1} selected={selected} onToggle={onToggle} />)}
    </div>
  );
}
