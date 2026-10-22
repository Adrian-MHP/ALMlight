import { useState } from "react";
import { Badge, Button, Card, Grid, Group, Modal, Select, SegmentedControl, Stack, Table, Text, Textarea, TextInput, Title } from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { api } from "@/api/client";
import { useBaseline, useBaselineCompare, useBaselines, useProjectMutation } from "@/api/hooks";
import { ItemLink, StateKeyBadge } from "@/components/badges";
import { ItemPicker } from "@/components/ItemPicker";
import { PageHeader } from "@/components/PageHeader";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "./ProjectLayout";
import { ChangeView } from "./item/HistoryTab";

export function BaselinesPage() {
  const { key, can } = useProjectCtx();
  const baselines = useBaselines(key).data ?? [];
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [compareTo, setCompareTo] = useState<string | null>("current");
  const detail = useBaseline(key, selected);
  const compare = useBaselineCompare(key, selected, compareTo === "current" ? null : compareTo);
  const [view, setView] = useState("compare");
  return (
    <>
      <PageHeader title="Baselines" subtitle="Frozen configurations of the project (or of a document / sub-structure) for reviews, releases and audits"
        actions={can("reviewer") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-baseline">New baseline</Button>} />
      <Grid>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Stack gap="xs">
            {baselines.map((b) => (
              <Card key={b.id} withBorder padding="sm" className="clickable" onClick={() => setSelected(b.id)}
                style={{ borderColor: selected === b.id ? "var(--mantine-primary-color-filled)" : undefined }} data-testid={`baseline-${b.name}`}>
                <Group justify="space-between"><Text fw={600}>{b.name}</Text><Badge size="xs" variant="light">{b.revision_rule}</Badge></Group>
                <Text size="xs" c="dimmed">{b.item_count} items · {b.link_count} links{b.scope ? ` · scope ${b.scope}` : ""}</Text>
                <Text size="xs" c="dimmed">{fmtDateTime(b.created_at)} by {b.created_by?.display_name}</Text>
              </Card>
            ))}
            {baselines.length === 0 && <Text c="dimmed">No baselines yet.</Text>}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 8 }}>
          {selected && detail.data ? (
            <Card withBorder>
              <Group justify="space-between" mb="sm">
                <div>
                  <Title order={4}>{detail.data.name}</Title>
                  <Text size="sm" c="dimmed">{detail.data.description}</Text>
                </div>
                <SegmentedControl value={view} onChange={setView} data={[{ value: "compare", label: "Compare" }, { value: "content", label: "Content" }]} />
              </Group>
              {view === "content" ? (
                <Table>
                  <Table.Thead><Table.Tr><Table.Th>Item</Table.Th><Table.Th>Baselined</Table.Th><Table.Th>State</Table.Th><Table.Th>Current</Table.Th></Table.Tr></Table.Thead>
                  <Table.Tbody>
                    {detail.data.items.map((i) => (
                      <Table.Tr key={i.id}>
                        <Table.Td><ItemLink item={i} withTitle /></Table.Td>
                        <Table.Td><Text size="sm" className="mono">{i.version}</Text></Table.Td>
                        <Table.Td><StateKeyBadge typeKey={i.type_key} state={i.state} /></Table.Td>
                        <Table.Td><Text size="sm" className="mono" c={i.current_version !== i.version ? "orange" : undefined}>{i.current_version}</Text></Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              ) : (
                <>
                  <Select label="Compare with" mb="md" w={320} value={compareTo} onChange={setCompareTo} allowDeselect={false}
                    data={[{ value: "current", label: "Current state" }, ...baselines.filter((b) => b.id !== selected).map((b) => ({ value: b.id, label: b.name }))]} />
                  {compare.data && (
                    <Stack data-testid="compare-result">
                      <Group gap="xs">
                        <Badge color="green" variant="light">{compare.data.items.added.length} added</Badge>
                        <Badge color="red" variant="light">{compare.data.items.removed.length} removed</Badge>
                        <Badge color="orange" variant="light">{compare.data.items.changed.length} changed</Badge>
                        <Badge color="gray" variant="light">{compare.data.items.unchanged} unchanged</Badge>
                        <Badge color="indigo" variant="light">links +{compare.data.links.added.length} / −{compare.data.links.removed.length}</Badge>
                      </Group>
                      {compare.data.items.changed.map((c) => (
                        <Card key={c.key} withBorder padding="sm">
                          <Group gap="xs" mb={6}><ItemLink item={c} withTitle /><Text size="xs" className="mono">{c.from_version} → {c.to_version}</Text></Group>
                          <Stack gap={6}>{c.changes.map((ch) => <ChangeView key={ch.field} change={ch} />)}</Stack>
                        </Card>
                      ))}
                      {compare.data.items.added.map((c) => <Group key={c.key} gap="xs"><Badge color="green" size="xs">added</Badge><ItemLink item={c} withTitle /></Group>)}
                      {compare.data.items.removed.map((c) => <Group key={c.key} gap="xs"><Badge color="red" size="xs">removed</Badge><Text size="sm" className="item-key">{c.key}</Text><Text size="sm">{c.title}</Text></Group>)}
                      {[...compare.data.links.added.map((l) => ({ ...l, kind: "+" })), ...compare.data.links.removed.map((l) => ({ ...l, kind: "−" }))].map((l, i) => (
                        <Text key={i} size="xs" className="mono">{l.kind} {l.source} {l.type} {l.target}</Text>
                      ))}
                    </Stack>
                  )}
                </>
              )}
            </Card>
          ) : <Text c="dimmed">Select a baseline to inspect or compare it.</Text>}
        </Grid.Col>
      </Grid>
      <CreateBaseline opened={creating} onClose={() => setCreating(false)} onCreated={setSelected} />
    </>
  );
}

function CreateBaseline({ opened, onClose, onCreated }: { opened: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const { key, model } = useProjectCtx();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState<string | null>(null);
  const [rule, setRule] = useState("latest");
  const scopeTypes = model.config.item_types.filter((t) => model.config.link_types.some((lt) => lt.structural && lt.sources.includes(t.key))).map((t) => t.key);
  const create = useProjectMutation(key, () => api.post<{ id: string }>(`/projects/${key}/baselines`, { name, description, scope, revision_rule: rule }), {
    success: "Baseline created", onSuccess: (b) => { onCreated(b.id); onClose(); setName(""); setDescription(""); setScope(null); },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="New baseline">
      <Stack>
        <TextInput label="Name" placeholder="e.g. Design review 1" required value={name} onChange={(e) => setName(e.currentTarget.value)} data-testid="baseline-name" />
        <Textarea label="Description" value={description} onChange={(e) => setDescription(e.currentTarget.value)} />
        <ItemPicker label="Scope (optional)" description="A document or structure root; empty = whole project" types={scopeTypes} value={scope} onChange={setScope} />
        <div>
          <Text size="sm" fw={500} mb={4}>Revision rule</Text>
          <SegmentedControl value={rule} onChange={setRule} data={[{ value: "latest", label: "Latest (working)" }, { value: "released", label: "Latest released" }]} />
        </div>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button onClick={() => create.mutate(undefined)} disabled={!name.trim()} loading={create.isPending} data-testid="baseline-create">Create</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
