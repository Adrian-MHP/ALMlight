import { Alert, Card, Group, Table, Text } from "@mantine/core";
import { useVerification } from "@/api/hooks";
import type { ItemDetail } from "@/api/types";
import { ItemLink, SuspectBadge, VerificationBadge } from "@/components/badges";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { tx } from "@/lib/i18n";

export function VerificationTab({ item }: { item: ItemDetail }) {
  const { key } = useProjectCtx();
  const { data } = useVerification(key, item.key);
  if (!data) return null;
  return (
    <>
      <Group mb="md" gap="sm">
        <Text fw={600}>{tx("Verification status")}</Text>
        <VerificationBadge status={data.status} />
      </Group>
      {data.status === "retest" && (
        <Alert color="orange" mb="md">{tx("Results are outdated: the item or a test case changed after the last execution. Re-run the tests and confirm the links.")}</Alert>
      )}
      {data.tests.length === 0 ? <Text c="dimmed">{tx("No test case verifies {key} yet. Add a “verified by” link on the Links tab.", { key: item.key })}</Text> : (
        <Card withBorder padding={0}>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>{tx("Test case")}</Table.Th><Table.Th>{tx("Status")}</Table.Th><Table.Th>{tx("Last result")}</Table.Th><Table.Th>{tx("Executed")}</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {data.tests.map((t) => (
                <Table.Tr key={t.key}>
                  <Table.Td><ItemLink item={t} withTitle /></Table.Td>
                  <Table.Td><Group gap={4}><VerificationBadge status={t.status} />{t.suspect && <SuspectBadge />}</Group></Table.Td>
                  <Table.Td><Text size="sm">{t.result ?? "–"}{t.tested_version ? tx(" (rev {tested_version})", { tested_version: t.tested_version }) : ""}</Text></Table.Td>
                  <Table.Td><Text size="xs">{fmtDateTime(t.executed_at)}</Text></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </>
  );
}
