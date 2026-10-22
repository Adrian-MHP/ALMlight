import { useMemo, useState } from "react";
import { ActionIcon, Button, Card, Group, Select, Stack, Table, Text, TextInput, Tooltip } from "@mantine/core";
import { IconCheck, IconPlus, IconTrash } from "@tabler/icons-react";
import { api } from "@/api/client";
import { useLinks, useProjectMutation } from "@/api/hooks";
import type { ItemDetail, LinkView } from "@/api/types";
import { ItemLink, StateBadge, SuspectBadge, TypeBadge } from "@/components/badges";
import { ItemPicker } from "@/components/ItemPicker";
import { useProjectCtx } from "../ProjectLayout";

export function LinksTab({ item }: { item: ItemDetail }) {
  const { key, model, can } = useProjectCtx();
  const links = useLinks(key, item.key).data ?? [];
  const groups = useMemo(() => {
    const g = new Map<string, LinkView[]>();
    for (const l of links) {
      const k = `${l.direction}:${l.type}`;
      g.set(k, [...(g.get(k) ?? []), l]);
    }
    return [...g.entries()];
  }, [links]);
  const confirm = useProjectMutation(key, (id: string) => api.post(`/projects/${key}/links/${id}/confirm`, {}), { success: "Link confirmed" });
  const remove = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/links/${id}`), { success: "Link removed" });

  return (
    <Stack>
      {can("contributor") && <AddLink item={item} />}
      {groups.length === 0 && <Text c="dimmed">No links yet.</Text>}
      {groups.map(([groupKey, rows]) => {
        const lt = model.link(rows[0].type);
        return (
          <Card withBorder key={groupKey} padding="sm">
            <Text fw={600} size="sm" mb={6}>
              {item.key} <Text span c="indigo" fw={700}>{rows[0].label}</Text>{" "}
              <Text span c="dimmed" size="xs">({rows.length}){lt?.description ? ` — ${lt.description}` : ""}</Text>
            </Text>
            <Table>
              <Table.Tbody>
                {rows.map((l) => (
                  <Table.Tr key={l.id} data-testid={`link-${l.type}-${l.other.key}`}>
                    <Table.Td w={120}><ItemLink item={l.other} /></Table.Td>
                    <Table.Td><Text size="sm" lineClamp={1}>{l.other.title}</Text></Table.Td>
                    <Table.Td w={180}><TypeBadge typeKey={l.other.type_key} /></Table.Td>
                    <Table.Td w={120}><StateBadge item={l.other} /></Table.Td>
                    <Table.Td w={70}><Text size="xs" className="mono">{l.other.version}</Text></Table.Td>
                    <Table.Td w={200}>
                      <Group gap={4} wrap="nowrap">
                        {Object.entries(l.attributes).map(([k, v]) => <Text key={k} size="xs" c="dimmed">{k}: {String(v)}</Text>)}
                        {l.applicability && <Text size="xs" className="mono" c="pink">{l.applicability}</Text>}
                        {l.suspect && <SuspectBadge reason={l.suspect_reason} />}
                      </Group>
                    </Table.Td>
                    <Table.Td w={80}>
                      {can("contributor") && (
                        <Group gap={2} wrap="nowrap" justify="flex-end">
                          {l.suspect && (
                            <Tooltip label="Reviewed — the link is still valid">
                              <ActionIcon variant="subtle" color="green" onClick={() => confirm.mutate(l.id)} data-testid="confirm-link"><IconCheck size={16} /></ActionIcon>
                            </Tooltip>
                          )}
                          <Tooltip label="Remove link">
                            <ActionIcon variant="subtle" color="red" onClick={() => remove.mutate(l.id)}><IconTrash size={16} /></ActionIcon>
                          </Tooltip>
                        </Group>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        );
      })}
    </Stack>
  );
}

function AddLink({ item }: { item: ItemDetail }) {
  const { key, model } = useProjectCtx();
  const options = model.linkOptions(item.type_key);
  const [choice, setChoice] = useState<string | null>(null);
  const [other, setOther] = useState<string | null>(null);
  const [crossProject, setCrossProject] = useState("");
  const opt = options.find((o) => o.value === choice);
  const add = useProjectMutation(key, () => {
    if (!opt) throw new Error("choose a link type");
    const otherRef = crossProject.trim() ? crossProject.trim().toUpperCase() : other!;
    const body = opt.direction === "outgoing"
      ? { type: opt.linkType, source: item.key, target: otherRef }
      : { type: opt.linkType, source: otherRef, target: item.key };
    return api.post(`/projects/${key}/links`, body);
  }, { success: "Link added", onSuccess: () => { setOther(null); setCrossProject(""); } });

  return (
    <Card withBorder padding="sm" bg="var(--mantine-color-default-hover)">
      <Group align="flex-end" wrap="wrap">
        <Select label="Relation" placeholder="Choose…" w={240} value={choice} onChange={(v) => { setChoice(v); setOther(null); }}
          data={options.map((o) => ({ value: o.value, label: `${o.label}${o.direction === "incoming" ? " (incoming)" : ""}` }))}
          data-testid="link-type" searchable />
        <div style={{ flex: 1, minWidth: 260 }}>
          <ItemPicker label="Item" types={opt?.otherTypes} value={other} onChange={setOther} exclude={[item.key]} testId="link-target" />
        </div>
        {opt?.direction === "outgoing" && (
          <TextInput label="or other project" placeholder="PLAT:SE-4" w={140} value={crossProject} onChange={(e) => setCrossProject(e.currentTarget.value)} />
        )}
        <Button leftSection={<IconPlus size={16} />} onClick={() => add.mutate(undefined)} loading={add.isPending}
          disabled={!opt || (!other && !crossProject.trim())} data-testid="link-add">Add link</Button>
      </Group>
      {opt && (
        <Text size="xs" c="dimmed" mt={6}>
          {opt.direction === "outgoing" ? `${item.key} ${opt.label} …` : `… ${model.link(opt.linkType)?.label} ${item.key}`}
          {" "}· allowed: {opt.otherTypes.map((t) => model.typeLabel(t)).join(", ")}
        </Text>
      )}
    </Card>
  );
}
