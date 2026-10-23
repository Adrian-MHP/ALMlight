import { useState } from "react";
import { ActionIcon, Button, Card, Group, Modal, NumberInput, Progress, SimpleGrid, Stack, Table, Text, TextInput } from "@mantine/core";
import { IconClock, IconPencil, IconTrash } from "@tabler/icons-react";
import { api } from "@/api/client";
import { useItemWork, useProjectMutation } from "@/api/hooks";
import type { ItemDetail, WorkRecord } from "@/api/types";
import { fmtDate } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { decimalSep, intlLocale, tx } from "@/lib/i18n";

const isoToday = () => new Date().toISOString().slice(0, 10);

/** Time recording on an item: estimate, spent and remaining effort, and the work records. */
export function TimeTab({ item }: { item: ItemDetail }) {
  const { key } = useProjectCtx();
  const work = useItemWork(key, item.key).data;
  const [day, setDay] = useState(isoToday());
  const [hours, setHours] = useState<number | string>(1);
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState<WorkRecord | null>(null);
  const record = useProjectMutation(key, () => api.post(`/projects/${key}/items/${item.key}/work`, { day, hours: Number(hours), comment: comment || null }),
    { success: tx("Recorded {hours} h on {key}", { hours: hours, key: item.key }), onSuccess: () => setComment("") });
  const remove = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/work/${id}`), { success: tx("Time record deleted") });
  if (!work) return null;
  const pct = work.estimate ? Math.min(100, (work.spent / work.estimate) * 100) : 0;
  return (
    <Stack data-testid="time-tab">
      <SimpleGrid cols={{ base: 1, xs: 3 }}>
        <Figure label={tx("Estimate")} value={work.estimate != null ? `${fmtH(work.estimate)} h` : "–"} />
        <Figure label={tx("Spent")} value={`${fmtH(work.spent)} h`} testId="time-spent" color={work.over ? "red" : undefined} />
        <Figure label={tx("Remaining")} value={work.remaining != null ? `${fmtH(work.remaining)} h` : "–"} testId="time-remaining" />
      </SimpleGrid>
      {work.estimate != null && <Progress value={pct} color={work.over ? "red" : "teal"} size="sm" aria-label={tx("Spent of estimate")} />}
      {work.can_record && (
        <Card withBorder padding="sm">
          <Group align="flex-end" wrap="wrap">
            <TextInput type="date" label={tx("Day")} value={day} max={isoToday()} onChange={(e) => setDay(e.currentTarget.value)} w={170} data-testid="time-day" />
            <NumberInput label={tx("Hours")} value={hours} onChange={setHours} min={0.25} max={24} step={0.25} decimalScale={2} decimalSeparator={decimalSep()} w={110} data-testid="time-hours" />
            <TextInput label={tx("Comment")} value={comment} onChange={(e) => setComment(e.currentTarget.value)} style={{ flex: 1, minWidth: 200 }} data-testid="time-comment" />
            <Button leftSection={<IconClock size={16} />} onClick={() => record.mutate(undefined)} loading={record.isPending}
              disabled={!day || !(Number(hours) > 0)} data-testid="time-record">{tx("Record time")}</Button>
          </Group>
        </Card>
      )}
      {work.by_user && work.by_user.length > 0 && (
        <Group gap="xs">
          {work.by_user.map((u) => <Text key={u.user?.id ?? "?"} size="sm" c="dimmed">{u.user?.display_name ?? "–"}: {fmtH(u.hours)} h</Text>)}
        </Group>
      )}
      <Card withBorder padding={0}>
        <Table.ScrollContainer minWidth={520}>
          <Table data-testid="time-records">
            <Table.Thead><Table.Tr><Table.Th>{tx("Day")}</Table.Th><Table.Th>{tx("Person")}</Table.Th><Table.Th>{tx("Hours")}</Table.Th><Table.Th>{tx("Comment")}</Table.Th><Table.Th w={70} /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {work.records.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td>{fmtDate(r.day)}</Table.Td>
                  <Table.Td>{r.user?.display_name ?? "–"}</Table.Td>
                  <Table.Td>{fmtH(r.hours)}</Table.Td>
                  <Table.Td><Text size="sm">{r.comment ?? ""}</Text></Table.Td>
                  <Table.Td>
                    {r.can_edit && (
                      <Group gap={2} wrap="nowrap">
                        <ActionIcon variant="subtle" color="gray" onClick={() => setEditing(r)} aria-label={tx("Change time record")}><IconPencil size={14} /></ActionIcon>
                        <ActionIcon variant="subtle" color="red" onClick={() => remove.mutate(r.id)} aria-label={tx("Delete time record")} data-testid="time-delete"><IconTrash size={14} /></ActionIcon>
                      </Group>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
              {work.records.length === 0 && <Table.Tr><Table.Td colSpan={5}><Text size="sm" c="dimmed">{tx("No time recorded{v} yet.", { v: work.all_visible ? "" : tx(" by you") })}</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>
      <Text size="xs" c="dimmed">
        {work.all_visible ? tx("As a project manager you see everybody's records.") : tx("You see your own records; the total includes everybody's time. Project managers see all records.")}
      </Text>
      {editing && <EditRecord record={editing} onClose={() => setEditing(null)} />}
    </Stack>
  );
}

function EditRecord({ record, onClose }: { record: WorkRecord; onClose: () => void }) {
  const { key } = useProjectCtx();
  const [day, setDay] = useState(record.day);
  const [hours, setHours] = useState<number | string>(record.hours);
  const [comment, setComment] = useState(record.comment ?? "");
  const save = useProjectMutation(key, () => api.patch(`/projects/${key}/work/${record.id}`, { day, hours: Number(hours), comment }),
    { success: tx("Time record changed"), onSuccess: onClose });
  return (
    <Modal opened onClose={onClose} title={tx("Change time record")}>
      <Stack>
        <TextInput type="date" label={tx("Day")} value={day} max={isoToday()} onChange={(e) => setDay(e.currentTarget.value)} />
        <NumberInput label={tx("Hours")} value={hours} onChange={setHours} min={0.25} max={24} step={0.25} decimalScale={2} decimalSeparator={decimalSep()} />
        <TextInput label={tx("Comment")} value={comment} onChange={(e) => setComment(e.currentTarget.value)} />
        <Group justify="flex-end"><Button onClick={() => save.mutate(undefined)} loading={save.isPending}>{tx("Save")}</Button></Group>
      </Stack>
    </Modal>
  );
}

function Figure({ label, value, testId, color }: { label: string; value: string; testId?: string; color?: string }) {
  return (
    <Card withBorder padding="sm">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Text size="xl" fw={700} c={color} data-testid={testId}>{value}</Text>
    </Card>
  );
}

/** Hours with up to two decimals in the user's number format (3,5 in German). */
export function fmtH(h: number): string {
  return new Intl.NumberFormat(intlLocale(), { maximumFractionDigits: 2 }).format(h);
}
