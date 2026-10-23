import { useState } from "react";
import { ActionIcon, Anchor, Badge, Button, Card, Code, CopyButton, Group, Select, Stack, Table, Text, TextInput, Tooltip } from "@mantine/core";
import { IconCheck, IconCopy, IconExternalLink, IconGitBranch, IconGitPullRequest, IconLink, IconTrash } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { pk, useProjectMutation } from "@/api/hooks";
import type { ItemDetail, ItemRevisions } from "@/api/types";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { tx } from "@/lib/i18n";
import { ProviderIcon } from "../CodePage";
import { useProjectCtx } from "../ProjectLayout";

/** Polarion "linked revisions": commits of the connected repositories that belong to this item, its branches and
 *  pull requests; link a commit by hand or start a branch for the item. */
export function RevisionsSection({ item }: { item: ItemDetail }) {
  const { key, can } = useProjectCtx();
  const qc = useQueryClient();
  const data = useQuery<ItemRevisions>({ queryKey: pk(key, "revisions", item.key), queryFn: () => api.get(`/projects/${key}/items/${item.key}/revisions`) }).data;
  const [repo, setRepo] = useState<string | null>(null);
  const [sha, setSha] = useState("");
  const [branch, setBranch] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: pk(key, "revisions", item.key) }); qc.invalidateQueries({ queryKey: pk(key, "repo") }); };
  const link = useProjectMutation(key, () => api.post(`/projects/${key}/items/${item.key}/revisions`, { repository: repo ?? data?.repositories[0]?.id, sha }), {
    success: tx("Revision linked"), onSuccess: () => { setSha(""); refresh(); },
  });
  const unlink = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/items/${item.key}/revisions/${id}`), { success: tx("Linked revision removed"), onSuccess: refresh });
  const create = useProjectMutation(key, (r: { repo: string; name: string }) => api.post<{ name: string }>(`/projects/${key}/repositories/${r.repo}/branches`, { name: r.name, item: item.key }), {
    success: (r) => tx("Branch {name} created", { name: r.name }), onSuccess: refresh,
  });
  if (!data) return null;
  if (data.repositories.length === 0) {
    return <Text size="sm" c="dimmed" mb="md">{tx("No Git repository is connected to this project — managers connect one on the Code page.")}</Text>;
  }
  const repoId = repo ?? data.repositories[0].id;
  const target = data.repositories.find((r) => r.id === repoId)!;
  const branchName = branch ?? data.branch_name;
  return (
    <Stack gap="sm" mb="lg" data-testid="revisions">
      <Group justify="space-between">
        <Text fw={600}>{tx("Linked revisions")} <Badge size="sm" variant="light">{data.revisions.length}</Badge></Text>
      </Group>
      <Card withBorder padding={0}>
        <Table.ScrollContainer minWidth={640}>
          <Table data-testid="revision-list">
            <Table.Tbody>
              {data.revisions.map((r) => (
                <Table.Tr key={r.link_id} data-testid={`revision-${r.short}`}>
                  <Table.Td w={30}><ProviderIcon provider={r.repository.provider} /></Table.Td>
                  <Table.Td w={96}><Anchor component={Link} to={`/p/${key}/code?repo=${r.repository.id}&commit=${r.sha}`} className="mono" size="sm">{r.short}</Anchor></Table.Td>
                  <Table.Td><Text size="sm" lineClamp={1}>{r.title}</Text><Text size="xs" c="dimmed">{r.repository.name} · {r.author}</Text></Table.Td>
                  <Table.Td w={120}><Tooltip label={fmtDateTime(r.committed_at)}><Text size="xs">{fmtRelative(r.committed_at)}</Text></Tooltip></Table.Td>
                  <Table.Td w={110}><Badge size="xs" variant={r.source === "manual" ? "outline" : "light"}>{r.source === "manual" ? tx("linked by hand") : tx("from message")}</Badge></Table.Td>
                  <Table.Td w={70}>
                    <Group gap={2} wrap="nowrap">
                      {r.url && <ActionIcon size="sm" variant="subtle" component="a" href={r.url} target="_blank" rel="noopener noreferrer" aria-label={tx("Open in {provider}", { provider: r.repository.provider })}><IconExternalLink size={14} /></ActionIcon>}
                      {r.source === "manual" && can("contributor") && <ActionIcon size="sm" variant="subtle" color="red" onClick={() => unlink.mutate(r.link_id)} aria-label={tx("Remove linked revision")} data-testid="revision-unlink"><IconTrash size={14} /></ActionIcon>}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
              {data.revisions.length === 0 && <Table.Tr><Table.Td><Text size="sm" c="dimmed">{tx("No commit mentions {key} yet. Write the key into the commit message, e.g. “{key}: add range check”, or link a commit below.", { key: item.key })}</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>
      {(data.branches.length > 0 || data.pull_requests.length > 0) && (
        <Group gap="xs" wrap="wrap">
          {data.branches.map((b) => (
            <Badge key={`${b.repository.id}-${b.name}`} variant="outline" size="lg" leftSection={<IconGitBranch size={12} />} style={{ textTransform: "none" }}
              component={Link} to={`/p/${key}/code?repo=${b.repository.id}&tab=files&ref=${encodeURIComponent(b.name)}`} className="clickable" data-testid="revision-branch">{b.name}</Badge>
          ))}
          {data.pull_requests.map((p) => (
            <Badge key={p.id} variant="light" size="lg" color={p.status === "merged" ? "grape" : p.status === "open" ? "teal" : "gray"} leftSection={<IconGitPullRequest size={12} />}
              style={{ textTransform: "none" }} component="a" href={p.url ?? undefined} target="_blank" className="clickable">{p.external_id} {p.title} · {p.status}</Badge>
          ))}
        </Group>
      )}
      {can("contributor") && (
        <Card withBorder padding="sm" bg="var(--mantine-color-default-hover)">
          <Group align="flex-end" wrap="wrap" gap="xs">
            {data.repositories.length > 1 && <Select label={tx("Repository")} size="xs" w={180} value={repoId} allowDeselect={false} onChange={setRepo}
              data={data.repositories.map((r) => ({ value: r.id, label: r.name }))} />}
            <TextInput label={tx("Link a commit")} size="xs" w={200} placeholder={tx("commit hash")} value={sha} onChange={(e) => setSha(e.currentTarget.value.trim())} data-testid="revision-sha" />
            <Button size="xs" leftSection={<IconLink size={14} />} disabled={sha.length < 4} onClick={() => link.mutate(undefined)} loading={link.isPending} data-testid="revision-link">{tx("Link")}</Button>
            <TextInput label={tx("Branch for this item")} size="xs" style={{ flex: 1, minWidth: 240 }} value={branchName} onChange={(e) => setBranch(e.currentTarget.value)} data-testid="revision-branch-name" />
            {target.can_push ? (
              <Button size="xs" variant="default" leftSection={<IconGitBranch size={14} />} onClick={() => create.mutate({ repo: repoId, name: branchName })} loading={create.isPending} data-testid="revision-create-branch">{tx("Create branch")}</Button>
            ) : (
              <CopyButton value={`git checkout -b ${branchName}`}>
                {({ copied, copy }) => <Tooltip label={tx("No write token: copy the command and create the branch locally")}><Button size="xs" variant="default" onClick={copy} leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />}>{copied ? tx("Copied") : <Code>git checkout -b</Code>}</Button></Tooltip>}
              </CopyButton>
            )}
          </Group>
        </Card>
      )}
    </Stack>
  );
}
