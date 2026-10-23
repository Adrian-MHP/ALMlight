import { Alert, Badge, Stack, Table, Text } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import type { ScheduleResult } from "@/api/types";
import { tx } from "@/lib/i18n";

const short = (d: string | null) => (d ? `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(2, 4)}` : "");

/** Preview/result of auto-scheduling or resource levelling: the moves and what remains in conflict. */
export function ScheduleTable({ result }: { result: ScheduleResult }) {
  return (
    <Stack gap="xs" data-testid="tl-sched-result">
      {result.moves.length === 0 ? <Text size="sm">{tx("Nothing to move.")}</Text> : (
        <Table.ScrollContainer minWidth={560}>
          <Table striped verticalSpacing={4}>
            <Table.Thead><Table.Tr><Table.Th>{tx("Item")}</Table.Th><Table.Th>{tx("Start")}</Table.Th><Table.Th>{tx("Finish")}</Table.Th><Table.Th>{tx("Shift")}</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {result.moves.map((m) => (
                <Table.Tr key={m.key} data-testid={`tl-move-${m.key}`}>
                  <Table.Td><Text size="sm"><span className="item-key">{m.key}</span> {m.title}</Text>{m.message && <Text size="xs" c="red">{m.message}</Text>}</Table.Td>
                  <Table.Td className="mono">{m.start_date[0] ? `${short(m.start_date[0])} → ${short(m.start_date[1])}` : ""}</Table.Td>
                  <Table.Td className="mono">{short(m.due_date[0])} → {short(m.due_date[1])}</Table.Td>
                  <Table.Td><Badge size="sm" variant="light" color={m.shift > 0 ? "orange" : "teal"} className="badge-keep">{m.shift > 0 ? "+" : ""}{m.shift} d</Badge></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {result.remaining_conflicts.length > 0 && (
        <Alert color="orange" icon={<IconAlertTriangle size={16} />} title={tx("Remaining conflicts")} data-testid="tl-sched-remaining">
          {result.remaining_conflicts.map((c) => <Text key={`${c.item}-${c.depends_on}`} size="sm">{c.message}</Text>)}
        </Alert>
      )}
    </Stack>
  );
}
