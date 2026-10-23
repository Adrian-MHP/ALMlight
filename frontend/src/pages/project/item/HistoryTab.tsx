import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Badge, Button, Card, Grid, Group, Radio, Stack, Table, Text, Timeline, Title } from "@mantine/core";
import { api } from "@/api/client";
import { useDiff, useHistory, useProjectMutation, useVersions } from "@/api/hooks";
import type { Change, ItemDetail } from "@/api/types";
import { RichDiff } from "@/components/rich/RichText";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { tx } from "@/lib/i18n";

export function HistoryTab({ item }: { item: ItemDetail }) {
  const { key, can } = useProjectCtx();
  const versions = useVersions(key, item.key).data ?? [];
  const history = useHistory(key, item.key).data ?? [];
  const [params] = useSearchParams();
  const [from, setFrom] = useState<number | null>(params.get("from") ? Number(params.get("from")) : null);
  const [to, setTo] = useState<number | null>(null);
  const diff = useDiff(key, item.key, from, to ?? item.version_no);
  const restore = useProjectMutation(key, (n: number) => api.post(`/projects/${key}/items/${item.key}/restore`,
    { version_no: n, expected_version: item.version_no }), { success: tx("Version restored as a new iteration") });

  return (
    <Grid>
      <Grid.Col span={{ base: 12, lg: 7 }}>
        <Card withBorder padding={0} mb="md">
          <Table data-testid="versions-table">
            <Table.Thead>
              <Table.Tr><Table.Th>{tx("From")}</Table.Th><Table.Th>{tx("To")}</Table.Th><Table.Th>{tx("Version")}</Table.Th><Table.Th>{tx("Change")}</Table.Th><Table.Th>{tx("Author")}</Table.Th><Table.Th /></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {versions.map((v) => (
                <Table.Tr key={v.version_no}>
                  <Table.Td w={40}><Radio size="xs" checked={from === v.version_no} onChange={() => setFrom(v.version_no)} aria-label={tx("compare from")} /></Table.Td>
                  <Table.Td w={40}><Radio size="xs" checked={(to ?? item.version_no) === v.version_no} onChange={() => setTo(v.version_no)} aria-label={tx("compare to")} /></Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <Text className="mono" size="sm" fw={600}>{v.version}</Text>
                      {v.released && <Badge size="xs" color="green">{tx("released")}</Badge>}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm"><Badge size="xs" variant="outline" mr={6}>{v.kind}</Badge>{v.change_note ?? ""}</Text>
                    {v.change_order && <Text size="xs" c="orange">{tx("under {change_order}", { change_order: v.change_order })}</Text>}
                  </Table.Td>
                  <Table.Td><Text size="xs">{v.created_by?.display_name}<br />{fmtDateTime(v.created_at)}</Text></Table.Td>
                  <Table.Td>
                    <Group gap={2} wrap="nowrap">
                      {v.version_no !== item.version_no && (
                        <Button size="xs" variant="subtle" component={Link} to={`/p/${key}/items/${item.key}?version=${v.version_no}`}
                          data-testid={`open-version-${v.version_no}`}>{tx("Open")}</Button>
                      )}
                      {can("contributor") && !item.lifecycle.frozen && v.version_no !== item.version_no && (
                        <Button size="xs" variant="subtle" onClick={() => restore.mutate(v.version_no)}>{tx("Restore")}</Button>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
        {from !== null && diff.data && (
          <Card withBorder data-testid="diff-panel">
            <Title order={5} mb="sm">{tx("Changes {from} → {to}", { from: diff.data.from, to: diff.data.to })}</Title>
            {diff.data.changes.length === 0 ? <Text c="dimmed" size="sm">{tx("No content differences.")}</Text> :
              <Stack gap="sm">{diff.data.changes.map((c) => <ChangeView key={c.field} change={c} />)}</Stack>}
          </Card>
        )}
        {from === null && <Text size="sm" c="dimmed">{tx("Select a “From” version to compare it with another version.")}</Text>}
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 5 }}>
        <Card withBorder>
          <Title order={5} mb="sm">{tx("Activity")}</Title>
          <Timeline bulletSize={14} lineWidth={2}>
            {history.map((h) => (
              <Timeline.Item key={h.id} title={<Text size="sm">{h.summary}</Text>}>
                <Text size="xs" c="dimmed">{h.actor} · {fmtDateTime(h.ts)}</Text>
              </Timeline.Item>
            ))}
          </Timeline>
        </Card>
      </Grid.Col>
    </Grid>
  );
}

export function ChangeView({ change }: { change: Change }) {
  if (change.html_diff) {
    return (
      <div>
        <Text size="xs" fw={600} mb={2}>{change.field}</Text>
        <div className="rich-diff-box" data-testid="html-diff"><RichDiff html={change.html_diff} /></div>
      </div>
    );
  }
  if (change.diff && change.diff.length) {
    return (
      <div>
        <Text size="xs" fw={600} mb={2}>{change.field}</Text>
        <div style={{ border: "1px solid var(--mantine-color-default-border)", borderRadius: 6, overflow: "hidden" }}>
          {change.diff.filter((l) => !l.startsWith("---") && !l.startsWith("+++")).map((l, i) => (
            <div key={i} className={`diff-line ${l.startsWith("+") ? "diff-add" : l.startsWith("-") ? "diff-del" : ""}`}>{l}</div>
          ))}
        </div>
      </div>
    );
  }
  const fmt = (v: unknown) => (v === null || v === undefined || v === "" ? "∅" : Array.isArray(v) ? v.join(", ") : String(v));
  return (
    <Group gap="xs" wrap="nowrap" align="flex-start">
      <Text size="xs" fw={600} w={140} style={{ flexShrink: 0 }}>{change.field}</Text>
      <Text size="sm" className="diff-del" style={{ borderRadius: 4 }}>{fmt(change.old)}</Text>
      <Text size="sm">→</Text>
      <Text size="sm" className="diff-add" style={{ borderRadius: 4 }}>{fmt(change.new)}</Text>
    </Group>
  );
}
