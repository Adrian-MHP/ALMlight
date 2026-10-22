import { useState } from "react";
import { Badge, Button, Card, Group, ScrollArea, SegmentedControl, Stack, Text } from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { useItems } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { stateColor } from "@/lib/model";
import { fmtRelative } from "@/lib/format";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";

/** Change management board: problem reports, change requests and change orders by lifecycle state. */
export function ChangesPage() {
  const { key, model, can } = useProjectCtx();
  const changeTypes = model.typesIn("change");
  const [type, setType] = useState<string>(changeTypes.find((t) => t.key === "change_request")?.key ?? changeTypes[0]?.key ?? "");
  const [creating, setCreating] = useState(false);
  const { data } = useItems(key, { type: [type], limit: 500, sort: "-updated" }, !!type);
  const wf = model.workflow(type);
  if (!changeTypes.length) return <Text c="dimmed">This project's information model has no change item types.</Text>;
  return (
    <>
      <PageHeader title="Changes" subtitle="Closed-loop change management: problem report → change request (impact analysis, CCB decision) → change order (implementation, release)"
        actions={can("contributor") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-change">New {model.typeLabel(type)}</Button>} />
      <SegmentedControl mb="md" value={type} onChange={setType} data={changeTypes.map((t) => ({ value: t.key, label: t.label }))} />
      <ScrollArea>
        <Group align="flex-start" wrap="nowrap" gap="sm" pb="sm">
          {(wf?.states ?? []).map((s) => {
            const cards = (data?.items ?? []).filter((i) => i.lifecycle.state === s.key);
            return (
              <Card key={s.key} withBorder className="kanban-col" padding="sm" bg="var(--mantine-color-default-hover)" data-testid={`col-${s.key}`}>
                <Group justify="space-between" mb="sm">
                  <Badge color={stateColor(s.color, s.category)} variant="light">{s.label}</Badge>
                  <Text size="xs" c="dimmed">{cards.length}</Text>
                </Group>
                <Stack gap="xs">
                  {cards.map((c) => (
                    <Card key={c.id} withBorder padding="xs" component={Link} to={`/p/${key}/items/${c.key}`} style={{ textDecoration: "none" }}>
                      <Group justify="space-between" gap={4}>
                        <Text className="item-key" size="xs">{c.key}</Text>
                        {typeof c.fields.priority === "string" && <Badge size="xs" variant="outline">{c.fields.priority}</Badge>}
                      </Group>
                      <Text size="sm" lineClamp={2}>{c.title}</Text>
                      <Text size="xs" c="dimmed">{c.owner?.display_name} · {fmtRelative(c.updated_at)}</Text>
                    </Card>
                  ))}
                </Stack>
              </Card>
            );
          })}
        </Group>
      </ScrollArea>
      <ItemFormModal opened={creating} onClose={() => setCreating(false)} defaultType={type} types={changeTypes.map((t) => t.key)} />
    </>
  );
}
