import { useEffect, useState } from "react";
import { ActionIcon, Badge, Button, Card, Group, NumberInput, Select, Table, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconChevronLeft, IconChevronRight, IconPlus } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ApiError } from "@/api/client";
import { pk, useMembers, useTimesheet } from "@/api/hooks";
import type { Timesheet, TimesheetRow } from "@/api/types";
import { ItemPicker } from "@/components/ItemPicker";
import { PageHeader } from "@/components/PageHeader";
import { fmtH } from "./item/TimeTab";
import { useProjectCtx } from "./ProjectLayout";
import { decimalSep, intlLocale, tm, tx } from "@/lib/i18n";

const DAY = 86400000;
const iso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (s: string, n: number) => iso(new Date(new Date(`${s}T00:00:00Z`).getTime() + n * DAY));

function mondayOf(s: string): string {
  const d = new Date(`${s}T00:00:00Z`);
  return addDays(s, -((d.getUTCDay() + 6) % 7));
}

/** Weekly timesheet (Polarion/Teamcenter style): hours per item and day, the open tasks of the week as rows. */
export function TimesheetPage() {
  const { key, model, can } = useProjectCtx();
  const qc = useQueryClient();
  const [week, setWeek] = useState(() => mondayOf(iso(new Date())));
  const [user, setUser] = useState<string | null>(null);
  const [extra, setExtra] = useState<string[]>([]);
  const [adding, setAdding] = useState<string | null>(null);
  const members = useMembers(key).data ?? [];
  const { data } = useTimesheet(key, week, user);
  const manager = can("manager");
  async function save(item: string, day: string, hours: number) {
    try {
      await api.put(`/projects/${key}/timesheet`, { item, day, hours });
      await qc.invalidateQueries({ queryKey: pk(key, "timesheet") });
      qc.invalidateQueries({ queryKey: pk(key, "work", item) });
      qc.invalidateQueries({ queryKey: pk(key, "resources") });
    } catch (e) {
      notifications.show({ color: "red", title: tx("{item}: not saved", { item: item }), message: e instanceof ApiError ? e.message : String(e) });
      await qc.invalidateQueries({ queryKey: pk(key, "timesheet") });
    }
  }
  const types = model.config.item_types.map((t) => t.key);
  const rows: TimesheetRow[] = data ? [...data.rows] : [];
  for (const k of extra) {
    if (!rows.some((r) => r.key === k)) {
      rows.push({ key: k, title: "", type_key: "", state_label: "", hours: {}, total: 0, estimate: null, spent: 0, remaining: null, done: false, over: false });
    }
  }
  return (
    <>
      <PageHeader title={tx("Timesheet")} subtitle={tx("Hours per item and day — your open tasks of the week are listed; add any other item you worked on")} />
      <Card withBorder mb="sm" padding="sm">
        <Group justify="space-between" wrap="wrap">
          <Group gap="xs">
            <ActionIcon variant="default" onClick={() => setWeek(addDays(week, -7))} aria-label={tx("Previous week")} data-testid="ts-prev"><IconChevronLeft size={16} /></ActionIcon>
            <Text fw={600} data-testid="ts-week">{tx("Week {week} · {week1} – {short}", { week: isoWeek(week), week1: short(week), short: short(addDays(week, 6)) })}</Text>
            <ActionIcon variant="default" onClick={() => setWeek(addDays(week, 7))} aria-label={tx("Next week")} data-testid="ts-next"><IconChevronRight size={16} /></ActionIcon>
            <Button size="xs" variant="subtle" onClick={() => setWeek(mondayOf(iso(new Date())))}>{tx("This week")}</Button>
          </Group>
          {manager && (
            <Select size="xs" w={240} placeholder={tx("My timesheet")} clearable value={user} onChange={setUser} data-testid="ts-user"
              data={members.map((m) => ({ value: m.username, label: m.display_name }))} />
          )}
        </Group>
      </Card>
      {data && (
        <Card withBorder padding={0}>
          <Table.ScrollContainer minWidth={820}>
            <Table data-testid="timesheet" verticalSpacing={4}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{tx("Item")}</Table.Th>
                  {data.days.map((d, i) => (
                    <Table.Th key={d} ta="center" w={78} className={d === data.today ? "ts-today" : i >= 5 ? "ts-weekend" : undefined}>
                      {weekday(d)}<Text size="xs" c="dimmed">{short(d)}</Text>
                    </Table.Th>
                  ))}
                  <Table.Th ta="right" w={70}>{tx("Week")}</Table.Th>
                  <Table.Th ta="right" w={120}>{tx("Remaining")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((r) => (
                  <Table.Tr key={r.key} data-testid={`ts-row-${r.key}`}>
                    <Table.Td>
                      <Text size="sm"><Link to={`/p/${key}/items/${r.key}?tab=time`} className="item-key">{r.key}</Link> {r.title}</Text>
                      {tm(r.state_label) && <Text size="xs" c="dimmed">{model.type(r.type_key)?.label} · {tm(r.state_label)}</Text>}
                    </Table.Td>
                    {data.days.map((d, i) => (
                      <Table.Td key={d} className={d === data.today ? "ts-today" : i >= 5 ? "ts-weekend" : undefined}>
                        <Cell value={r.hours[d] ?? 0} disabled={!data.editable || d > data.today} testId={`ts-cell-${r.key}-${d}`}
                          onSave={(h) => save(r.key, d, h)} />
                      </Table.Td>
                    ))}
                    <Table.Td ta="right" fw={600}>{fmtH(r.total)}</Table.Td>
                    <Table.Td ta="right">
                      {r.remaining != null ? <Text size="sm" c={r.over ? "red" : undefined}>{fmtH(r.remaining)} h</Text> : <Text size="sm" c="dimmed">–</Text>}
                    </Table.Td>
                  </Table.Tr>
                ))}
                {rows.length === 0 && <Table.Tr><Table.Td colSpan={10}><Text size="sm" c="dimmed">{tx("No open tasks this week and no time recorded.")}</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
              <Table.Tfoot>
                <Table.Tr>
                  <Table.Th>{tx("Total")}</Table.Th>
                  {data.days.map((d) => <Table.Th key={d} ta="center" data-testid={`ts-total-${d}`}>{fmtH(data.totals[d] ?? 0)}</Table.Th>)}
                  <Table.Th ta="right" data-testid="ts-total">{fmtH(data.total)}</Table.Th>
                  <Table.Th ta="right"><Capacity data={data} /></Table.Th>
                </Table.Tr>
              </Table.Tfoot>
            </Table>
          </Table.ScrollContainer>
        </Card>
      )}
      {data?.editable && (
        <Group mt="sm" align="flex-end">
          <ItemPicker label={tx("Add an item")} w={340} types={types} value={adding} onChange={setAdding} exclude={rows.map((r) => r.key)} testId="ts-add-picker" />
          <Button leftSection={<IconPlus size={16} />} disabled={!adding} onClick={() => { setExtra((x) => [...x, adding!]); setAdding(null); }} data-testid="ts-add">{tx("Add row")}</Button>
        </Group>
      )}
    </>
  );
}

function Capacity({ data }: { data: Timesheet }) {
  const pct = data.capacity ? Math.round((data.total / data.capacity) * 100) : 0;
  return (
    <Tooltip label={tx("{total} of {capacity} h ({hours_per_day} h per working day)", { total: fmtH(data.total), capacity: fmtH(data.capacity), hours_per_day: fmtH(data.hours_per_day) })}>
      <Badge variant="light" color={pct > 100 ? "red" : pct >= 80 ? "teal" : "gray"} className="badge-keep">{pct} %</Badge>
    </Tooltip>
  );
}

function Cell({ value, disabled, testId, onSave }: { value: number; disabled: boolean; testId: string; onSave: (h: number) => void }) {
  const [v, setV] = useState<number | string>(value || "");
  useEffect(() => { setV(value || ""); }, [value]);
  const commit = () => {
    const n = v === "" ? 0 : Number(v);
    if (Number.isFinite(n) && n !== value) onSave(n);
  };
  return (
    <NumberInput size="xs" value={v} onChange={setV} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
      min={0} max={24} step={0.5} decimalScale={2} decimalSeparator={decimalSep()} hideControls disabled={disabled} styles={{ input: { textAlign: "center" } }}
      data-testid={testId} aria-label={testId} />
  );
}

function weekday(s: string): string {
  return new Date(`${s}T00:00:00Z`).toLocaleDateString(intlLocale(), { weekday: "short", timeZone: "UTC" });
}

function short(s: string): string {
  return `${s.slice(8, 10)}.${s.slice(5, 7)}.`;
}

function isoWeek(s: string): number {
  const t = new Date(`${s}T00:00:00Z`);
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t.getTime() - y.getTime()) / DAY + 1) / 7);
}
