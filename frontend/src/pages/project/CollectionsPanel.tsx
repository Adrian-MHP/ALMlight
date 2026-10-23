import { useState } from "react";
import { ActionIcon, Badge, Button, Card, Grid, Group, Menu, Modal, Select, Stack, Table, Text, Textarea, TextInput, Title } from "@mantine/core";
import { IconDownload, IconLock, IconLockOpen, IconPlus, IconTrash } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { api, downloadUrl } from "@/api/client";
import { useBaselines, useCollections, useItems, useProjectMutation } from "@/api/hooks";
import type { DocCollection } from "@/api/types";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "./ProjectLayout";
import { tx } from "@/lib/i18n";

/** Collections: release packages of document baselines; closing freezes them, only managers reopen. */
export function CollectionsPanel() {
  const { key, can } = useProjectCtx();
  const collections = useCollections(key).data ?? [];
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const current = collections.find((c) => c.id === selected) ?? collections[0];
  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 4 }}>
        <Stack gap="xs">
          {can("reviewer") && <Button leftSection={<IconPlus size={16} />} variant="light" onClick={() => setCreating(true)} data-testid="new-collection">{tx("New collection")}</Button>}
          {collections.map((c) => (
            <Card key={c.id} withBorder padding="sm" className="clickable" onClick={() => setSelected(c.id)} data-testid={`collection-${c.name}`}
              style={{ borderColor: current?.id === c.id ? "var(--mantine-primary-color-filled)" : undefined }}>
              <Group justify="space-between"><Text fw={600}>{c.name}</Text>
                <Badge size="xs" color={c.status === "closed" ? "gray" : "green"} variant="light" leftSection={c.status === "closed" ? <IconLock size={10} /> : undefined}>{c.status}</Badge></Group>
              <Text size="xs" c="dimmed">{tx("{length} document(s) · {created_at}", { length: c.entries.length, created_at: fmtDateTime(c.created_at) })}</Text>
            </Card>
          ))}
          {collections.length === 0 && <Text c="dimmed" size="sm">{tx("No collections yet. A collection groups document baselines that are released together.")}</Text>}
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 8 }}>{current && <CollectionDetail c={current} />}</Grid.Col>
      <CreateCollection opened={creating} onClose={() => setCreating(false)} onCreated={setSelected} />
    </Grid>
  );
}

function CollectionDetail({ c }: { c: DocCollection }) {
  const { key, model, can } = useProjectCtx();
  const baselines = useBaselines(key).data ?? [];
  const docs = useItems(key, { type: model.documentTypes.map((t) => t.key), limit: 200 }).data?.items ?? [];
  const [doc, setDoc] = useState<string | null>(null);
  const [baseline, setBaseline] = useState<string | null>(null);
  const add = useProjectMutation(key, () => api.post(`/projects/${key}/collections/${c.id}/documents`, { document: doc, baseline }),
    { success: tx("Document added"), onSuccess: () => { setDoc(null); setBaseline(null); } });
  const remove = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/collections/${c.id}/documents/${id}`));
  const status = useProjectMutation(key, (s: string) => api.post(`/projects/${key}/collections/${c.id}/status`, { status: s }),
    { success: (r) => tx("Collection {status}", { status: (r as DocCollection).status }) });
  const del = useProjectMutation(key, () => api.del(`/projects/${key}/collections/${c.id}`), { success: tx("Collection deleted") });
  const open = c.status === "open";
  return (
    <Card withBorder data-testid="collection-detail">
      <Group justify="space-between" mb="xs">
        <div>
          <Title order={4}>{c.name}</Title>
          <Text size="sm" c="dimmed">{c.description}</Text>
          {c.closed_at && <Text size="xs" c="dimmed">{tx("Closed {closed_at} by {display_name}", { closed_at: fmtDateTime(c.closed_at), display_name: c.closed_by?.display_name })}</Text>}
        </div>
        <Group gap="xs">
          <Menu>
            <Menu.Target><Button variant="default" size="xs" leftSection={<IconDownload size={14} />} disabled={!c.entries.length}>{tx("Export")}</Button></Menu.Target>
            <Menu.Dropdown>
              <Menu.Item component="a" href={downloadUrl(`/projects/${key}/collections/${c.id}/export.zip?format=pdf`)}>{tx("All documents as PDF (zip)")}</Menu.Item>
              <Menu.Item component="a" href={downloadUrl(`/projects/${key}/collections/${c.id}/export.zip?format=docx`)}>{tx("All documents as Word (zip)")}</Menu.Item>
            </Menu.Dropdown>
          </Menu>
          {open && can("reviewer") && <Button size="xs" leftSection={<IconLock size={14} />} onClick={() => status.mutate("closed")} data-testid="collection-close">{tx("Close (freeze)")}</Button>}
          {!open && can("manager") && <Button size="xs" variant="light" leftSection={<IconLockOpen size={14} />} onClick={() => status.mutate("open")}>{tx("Reopen")}</Button>}
          {open && can("manager") && <ActionIcon variant="subtle" color="red" onClick={() => del.mutate(undefined)}><IconTrash size={16} /></ActionIcon>}
        </Group>
      </Group>
      <Table>
        <Table.Thead><Table.Tr><Table.Th>{tx("Document")}</Table.Th><Table.Th>{tx("Baseline")}</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {c.entries.map((e) => (
            <Table.Tr key={e.id}>
              <Table.Td><Link to={`/p/${key}/documents/${e.document}?baseline=${e.baseline_id}`} className="item-key">{e.document}</Link> <Text span size="sm">{e.title}</Text></Table.Td>
              <Table.Td><Text size="sm">{e.baseline}</Text><Text size="xs" c="dimmed">{fmtDateTime(e.baseline_created_at)}</Text></Table.Td>
              <Table.Td w={40}>{open && can("reviewer") && <ActionIcon variant="subtle" color="red" onClick={() => remove.mutate(e.id)}><IconTrash size={14} /></ActionIcon>}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {open && can("reviewer") && (
        <Group align="flex-end" mt="sm">
          <Select label={tx("Document")} placeholder={tx("Choose…")} searchable value={doc} onChange={setDoc} w={260}
            data={docs.map((d) => ({ value: d.key, label: `${d.key} — ${d.title}` }))} data-testid="collection-doc" />
          <Select label={tx("Baseline")} placeholder={tx("New baseline now")} clearable value={baseline} onChange={setBaseline} w={260}
            data={baselines.map((b) => ({ value: b.id, label: `${b.name}${b.scope ? ` (${b.scope})` : ""}` }))} />
          <Button onClick={() => add.mutate(undefined)} disabled={!doc} loading={add.isPending} data-testid="collection-add">{tx("Add")}</Button>
        </Group>
      )}
    </Card>
  );
}

function CreateCollection({ opened, onClose, onCreated }: { opened: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const { key } = useProjectCtx();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = useProjectMutation(key, () => api.post<DocCollection>(`/projects/${key}/collections`, { name, description }), {
    success: tx("Collection created"), onSuccess: (c) => { onCreated(c.id); onClose(); setName(""); setDescription(""); },
  });
  return (
    <Modal opened={opened} onClose={onClose} title={tx("New collection")}>
      <Stack>
        <TextInput label={tx("Name")} placeholder={tx("e.g. Release 2.0")} value={name} onChange={(e) => setName(e.currentTarget.value)} data-testid="collection-name" />
        <Textarea label={tx("Description")} value={description} onChange={(e) => setDescription(e.currentTarget.value)} />
        <Group justify="flex-end"><Button onClick={() => create.mutate(undefined)} disabled={!name.trim()} loading={create.isPending} data-testid="collection-create">{tx("Create")}</Button></Group>
      </Stack>
    </Modal>
  );
}
