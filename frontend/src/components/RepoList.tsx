import { Anchor, Badge, Group, Table, Text, Tooltip } from "@mantine/core";
import { Link } from "react-router-dom";
import { useRepos } from "@/api/hooks";
import type { Repo } from "@/api/types";
import { ProviderIcon } from "@/components/ProviderIcon";
import { fmtRelative } from "@/lib/format";
import { tx } from "@/lib/i18n";

/** How a connected repository is doing: shown as a badge next to its name. */
export function repoStatus(r: Repo): { color: string; label: string } {
  if (!r.enabled) return { color: "gray", label: tx("Disabled") };
  if (r.last_error) return { color: "red", label: tx("Sync error") };
  if (!r.last_sync_at) return { color: "yellow", label: tx("Not fetched yet") };
  return { color: "teal", label: tx("In sync") };
}

/** The Git repositories connected to a project, with their state; each opens on the Code page. */
export function RepoList({ projectKey, compact = false }: { projectKey: string; compact?: boolean }) {
  const repos = useRepos(projectKey).data;
  if (!repos) return null;
  if (!repos.length) return <Text size="sm" c="dimmed" data-testid="repo-list-empty">{tx("No repository connected yet.")}</Text>;
  return (
    <Table.ScrollContainer minWidth={compact ? 300 : 560}>
      <Table verticalSpacing={6} data-testid="repo-list">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{tx("Repository")}</Table.Th>
            <Table.Th>{tx("Status")}</Table.Th>
            <Table.Th ta="right">{tx("Commits")}</Table.Th>
            {!compact && <Table.Th>{tx("Last fetch")}</Table.Th>}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {repos.map((r) => {
            const st = repoStatus(r);
            return (
              <Table.Tr key={r.id} data-testid={`repo-row-${r.name}`}>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    <ProviderIcon provider={r.provider} />
                    <div style={{ minWidth: 0 }}>
                      <Anchor component={Link} to={`/p/${projectKey}/code?repo=${r.id}`} size="sm" fw={600} title={tx("Show in Code")}>{r.name}</Anchor>
                      {!compact && <Text size="xs" c="dimmed" truncate maw={340}>{r.url}</Text>}
                    </div>
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Tooltip label={r.last_error ?? st.label} disabled={!r.last_error} multiline maw={360}>
                    <Badge color={st.color} variant="light" data-testid={`repo-state-${r.name}`}>{st.label}</Badge>
                  </Tooltip>
                </Table.Td>
                <Table.Td ta="right">{r.commit_count}</Table.Td>
                {!compact && <Table.Td><Text size="sm">{r.last_sync_at ? fmtRelative(r.last_sync_at) : tx("never")}</Text></Table.Td>}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
