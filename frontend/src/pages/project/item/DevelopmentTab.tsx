import { useState } from "react";
import { ActionIcon, Anchor, Badge, Button, Card, Group, Select, Table, Text, TextInput } from "@mantine/core";
import { IconBrandGithub, IconBrandAzure, IconLink, IconPlus, IconTrash } from "@tabler/icons-react";
import { api } from "@/api/client";
import { useProjectMutation, useRefs } from "@/api/hooks";
import type { ItemDetail } from "@/api/types";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";

const SYSTEMS = [
  { value: "github", label: "GitHub" }, { value: "gitlab", label: "GitLab" }, { value: "azure_devops", label: "Azure DevOps" },
  { value: "git", label: "Git" }, { value: "cad", label: "CAD" }, { value: "pdm", label: "PDM" }, { value: "ci", label: "CI/CD" },
  { value: "url", label: "Web link" }, { value: "other", label: "Other" },
];

function SystemIcon({ system }: { system: string }) {
  if (system === "github") return <IconBrandGithub size={16} />;
  if (system === "azure_devops") return <IconBrandAzure size={16} />;
  return <IconLink size={16} />;
}

export function DevelopmentTab({ item }: { item: ItemDetail }) {
  const { key, can } = useProjectCtx();
  const refs = useRefs(key, item.key).data ?? [];
  const [system, setSystem] = useState<string | null>("url");
  const [kind, setKind] = useState("link");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const add = useProjectMutation(key, () => api.post(`/projects/${key}/items/${item.key}/external-refs`, { system, kind, url: url || null, title: title || null }),
    { success: "Reference added", onSuccess: () => { setUrl(""); setTitle(""); } });
  const del = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/items/${item.key}/external-refs/${id}`));
  return (
    <>
      <Text size="sm" c="dimmed" mb="sm">
        Commits, pull requests, builds, work items and CAD/PDM artefacts linked to {item.key}. Integrations add them automatically when
        a commit message, branch or work item mentions <span className="item-key">{item.key}</span>.
      </Text>
      {can("contributor") && (
        <Card withBorder padding="sm" mb="md" bg="var(--mantine-color-default-hover)">
          <Group align="flex-end" wrap="wrap">
            <Select label="System" data={SYSTEMS} value={system} onChange={setSystem} w={150} allowDeselect={false} />
            <TextInput label="Kind" value={kind} onChange={(e) => setKind(e.currentTarget.value)} w={130} placeholder="cad_model" />
            <TextInput label="URL" value={url} onChange={(e) => setUrl(e.currentTarget.value)} style={{ flex: 1, minWidth: 220 }} placeholder="https://…" />
            <TextInput label="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} w={220} />
            <Button leftSection={<IconPlus size={16} />} onClick={() => add.mutate(undefined)} disabled={!url && !title}>Add</Button>
          </Group>
        </Card>
      )}
      {refs.length === 0 ? <Text c="dimmed">No external references.</Text> : (
        <Card withBorder padding={0}>
          <Table>
            <Table.Tbody>
              {refs.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td w={30}><SystemIcon system={r.system} /></Table.Td>
                  <Table.Td w={120}><Badge variant="light" size="sm">{r.kind}</Badge></Table.Td>
                  <Table.Td>{r.url ? <Anchor href={r.url} target="_blank" rel="noopener noreferrer" size="sm">{r.title || r.url}</Anchor> : <Text size="sm">{r.title}</Text>}
                    <Text size="xs" c="dimmed">{[r.data.repository, r.external_id].filter(Boolean).join(" · ")}</Text></Table.Td>
                  <Table.Td w={110}>{r.status && <Badge size="sm" variant="outline">{r.status}</Badge>}</Table.Td>
                  <Table.Td w={150}><Text size="xs">{fmtDateTime(r.updated_at)}</Text></Table.Td>
                  <Table.Td w={40}>{can("contributor") && <ActionIcon variant="subtle" color="red" onClick={() => del.mutate(r.id)}><IconTrash size={14} /></ActionIcon>}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </>
  );
}
