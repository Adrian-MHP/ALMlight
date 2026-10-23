import { useState } from "react";
import { Card, Code, Select, Table, Text, Tooltip } from "@mantine/core";
import { useAudit } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "./ProjectLayout";
import { tx } from "@/lib/i18n";

const ACTIONS = [
  { value: "item.", label: tx("Items") }, { value: "link.", label: tx("Links") }, { value: "approval.", label: tx("Approvals") },
  { value: "baseline.", label: tx("Baselines") }, { value: "project.", label: tx("Project") }, { value: "member.", label: tx("Members") },
  { value: "integration.", label: tx("Integrations") }, { value: "testrun.", label: tx("Test runs") },
];

export function ActivityPage() {
  const { key } = useProjectCtx();
  const [action, setAction] = useState<string | null>(null);
  const entries = useAudit(key, action).data ?? [];
  return (
    <>
      <PageHeader title={tx("Activity")} subtitle={tx("Tamper-evident audit trail — every change with who, when and what (hash-chained)")}
        actions={<Select placeholder={tx("All actions")} data={ACTIONS} value={action} onChange={setAction} clearable w={200} />} />
      <Card withBorder padding={0}>
        <Table data-testid="audit-table">
          <Table.Thead><Table.Tr><Table.Th w={170}>{tx("When")}</Table.Th><Table.Th w={120}>{tx("Who")}</Table.Th><Table.Th w={170}>{tx("Action")}</Table.Th><Table.Th>{tx("Summary")}</Table.Th><Table.Th w={90}>{tx("Hash")}</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {entries.map((e) => (
              <Table.Tr key={e.id}>
                <Table.Td><Text size="xs">{fmtDateTime(e.ts)}</Text></Table.Td>
                <Table.Td><Text size="sm">{e.actor}</Text></Table.Td>
                <Table.Td><Code>{e.action}</Code></Table.Td>
                <Table.Td><Text size="sm">{e.summary}</Text></Table.Td>
                <Table.Td><Tooltip label={e.hash}><Text size="xs" className="mono" c="dimmed">{e.hash.slice(0, 8)}</Text></Tooltip></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </>
  );
}
