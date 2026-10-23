import { useState } from "react";
import { ActionIcon, Alert, Button, Card, Group, Modal, ScrollArea, SegmentedControl, Select, Stack, Table, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconChevronLeft, IconChevronRight, IconScale } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ApiError } from "@/api/client";
import { pk, useResources } from "@/api/hooks";
import type { LevelResult, ResourceCell, Resources, Timeline } from "@/api/types";
import { ScheduleTable } from "@/components/ScheduleTable";
import { fmtH } from "./item/TimeTab";
import { useProjectCtx } from "./ProjectLayout";
import { tx } from "@/lib/i18n";

const DAY = 86400000;
const addDays = (s: string, n: number) => new Date(new Date(`${s}T00:00:00Z`).getTime() + n * DAY).toISOString().slice(0, 10);
const short = (s: string) => `${s.slice(8, 10)}.${s.slice(5, 7)}.`;

function level(load: number | null): string {
  if (!load) return "rs-l0";
  if (load > 1.0001) return "rs-l4";
  if (load > 0.9) return "rs-l3";
  if (load > 0.6) return "rs-l2";
  return "rs-l1";
}

/** Resource load per person and week against capacity (Teamcenter resource graph), with levelling. */
export function ResourceView({ timeline }: { timeline: Timeline }) {
  const { key, can } = useProjectCtx();
  const [weeks, setWeeks] = useState("12");
  const [start, setStart] = useState<string | null>(null);
  const [sel, setSel] = useState<{ user: string; week: string } | null>(null);
  const [leveling, setLeveling] = useState(false);
  const { data } = useResources(key, start, Number(weeks));
  if (!data) return null;
  const first = start ?? data.start;
  const cols = `minmax(150px, 200px) repeat(${data.weeks.length}, minmax(58px, 1fr))`;
  const person = sel && data.people.find((p) => p.user.id === sel.user);
  const cell = person && person.weeks.find((w) => w.week === sel!.week);
  const overloaded = data.people.reduce((n, p) => n + p.overloaded, 0);
  return (
    <Stack gap="sm" data-testid="resources">
      <Card withBorder padding="sm">
        <Group justify="space-between" wrap="wrap">
          <Group gap="xs">
            <ActionIcon variant="default" onClick={() => setStart(addDays(first, -28))} aria-label={tx("Earlier weeks")}><IconChevronLeft size={16} /></ActionIcon>
            <Text size="sm" fw={600}>{short(data.weeks[0])} – {short(addDays(data.weeks[data.weeks.length - 1], 6))}</Text>
            <ActionIcon variant="default" onClick={() => setStart(addDays(first, 28))} aria-label={tx("Later weeks")}><IconChevronRight size={16} /></ActionIcon>
            <Button size="xs" variant="subtle" onClick={() => setStart(null)}>{tx("Today")}</Button>
            <SegmentedControl size="xs" value={weeks} onChange={setWeeks} data={[{ value: "8", label: tx("8 weeks") }, { value: "12", label: tx("12 weeks") }, { value: "26", label: tx("26 weeks") }]} />
          </Group>
          <Group gap="md">
            <Group gap={4}><span className="tl-sw rs-l1" /><Text size="xs" c="dimmed">≤ 60 %</Text></Group>
            <Group gap={4}><span className="tl-sw rs-l2" /><Text size="xs" c="dimmed">≤ 90 %</Text></Group>
            <Group gap={4}><span className="tl-sw rs-l3" /><Text size="xs" c="dimmed">≤ 100 %</Text></Group>
            <Group gap={4}><span className="tl-sw rs-l4" /><Text size="xs" c="dimmed">{tx("overloaded")}</Text></Group>
            {can("contributor") && (
              <Button size="xs" leftSection={<IconScale size={14} />} onClick={() => setLeveling(true)} data-testid="rs-level">{tx("Level resources")}</Button>
            )}
          </Group>
        </Group>
      </Card>
      {overloaded > 0 && (
        <Alert color="red" icon={<IconAlertTriangle size={16} />} py="xs" data-testid="rs-overloads">
          {tx("{overloaded} overloaded person-week(s) — open a red cell to see the tasks, or level the resources.", { overloaded: overloaded })}</Alert>
      )}
      <Card withBorder padding="xs">
        <ScrollArea type="auto">
          <div className="rs-grid" style={{ gridTemplateColumns: cols, minWidth: 150 + data.weeks.length * 60 }}>
            <div />
            {data.weeks.map((w) => <div key={w} className="rs-head">{short(w)}</div>)}
            {data.people.map((p) => (
              <Row key={p.user.id} name={p.user.display_name} sub={tx("{hours_per_day} h/day{v}", { hours_per_day: fmtH(p.hours_per_day), v: p.member ? "" : tx(" · not a member") })}>
                {p.weeks.map((c) => (
                  <CellView key={c.week} c={c} selected={sel?.user === p.user.id && sel.week === c.week}
                    onClick={() => setSel(sel?.user === p.user.id && sel.week === c.week ? null : { user: p.user.id, week: c.week })}
                    testId={`rs-cell-${p.user.username}-${c.week}`} />
                ))}
              </Row>
            ))}
            {data.unassigned.some((u) => u.planned) && (
              <Row name={tx("Unassigned")} sub={tx("tasks without owner")}>
                {data.unassigned.map((u) => (
                  <Tooltip key={u.week} label={u.items.map((i) => `${i.key} ${fmtH(i.hours)} h`).join(", ") || "–"} disabled={!u.planned}>
                    <div className={`rs-cell ${u.planned ? "rs-l1" : "rs-l0"}`}>{u.planned ? `${fmtH(u.planned)} h` : ""}</div>
                  </Tooltip>
                ))}
              </Row>
            )}
          </div>
          {data.people.length === 0 && <Text size="sm" c="dimmed" p="sm">{tx("No people with planned or recorded work.")}</Text>}
        </ScrollArea>
      </Card>
      {person && cell && (
        <Card withBorder padding="sm" data-testid="rs-detail">
          <Text fw={600} size="sm">{tx("{display_name} · week of {week}: {planned} of {capacity} h planned{v} · {actual} h recorded", { display_name: person.user.display_name, week: short(cell.week), planned: fmtH(cell.planned), capacity: fmtH(cell.capacity), v: cell.load != null ? ` (${Math.round(cell.load * 100)} %)` : "", actual: fmtH(cell.actual) })}</Text>
          <Table mt="xs" verticalSpacing={2}>
            <Table.Tbody>
              {cell.items.map((i) => (
                <Table.Tr key={i.key}>
                  <Table.Td><Link to={`/p/${key}/items/${i.key}`} className="item-key">{i.key}</Link> {i.title}</Table.Td>
                  <Table.Td ta="right" w={80}>{fmtH(i.hours)} h</Table.Td>
                </Table.Tr>
              ))}
              {cell.items.length === 0 && <Table.Tr><Table.Td><Text size="sm" c="dimmed">{tx("No planned tasks this week.")}</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Card>
      )}
      <Text size="xs" c="dimmed">
        {tx("Planned load: remaining work of open tasks (estimate − recorded time, in hours) spread over their working days from today; tasks without an estimate count as full-time. Capacity: hours per day of each member (Settings → Members) × 5.")}
      </Text>
      {leveling && <LevelModal data={data} timeline={timeline} onClose={() => setLeveling(false)} />}
    </Stack>
  );
}

function Row({ name, sub, children }: { name: string; sub: string; children: React.ReactNode }) {
  return (
    <>
      <div className="rs-name"><Text size="sm" fw={500} truncate>{name}</Text><Text size="xs" c="dimmed" truncate>{sub}</Text></div>
      {children}
    </>
  );
}

function CellView({ c, selected, onClick, testId }: { c: ResourceCell; selected: boolean; onClick: () => void; testId: string }) {
  const pct = c.load != null ? Math.round(c.load * 100) : 0;
  return (
    <Tooltip label={tx("{planned} / {capacity} h planned · {actual} h recorded", { planned: fmtH(c.planned), capacity: fmtH(c.capacity), actual: fmtH(c.actual) })} openDelay={300}>
      <div className={`rs-cell ${level(c.load)}`} onClick={onClick} data-testid={testId} data-load={pct}
        style={selected ? { outline: "2px solid var(--mantine-color-blue-6)" } : undefined} role="button" tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter") onClick(); }}>
        {c.planned ? <><span>{pct} %</span><span style={{ fontSize: 10, opacity: 0.8 }}>{fmtH(c.planned)} h</span></> : c.actual ? <span style={{ fontSize: 10 }}>{fmtH(c.actual)} h ✓</span> : ""}
      </div>
    </Tooltip>
  );
}

function LevelModal({ data, timeline, onClose }: { data: Resources; timeline: Timeline; onClose: () => void }) {
  const { key } = useProjectCtx();
  const qc = useQueryClient();
  const [plan, setPlan] = useState<string | null>(null);
  const [result, setResult] = useState<LevelResult | null>(null);
  const [busy, setBusy] = useState(false);
  const plans = timeline.rows.filter((r) => r.kind === "release" || r.kind === "iteration").map((r) => ({ value: r.key, label: `${r.key} ${r.title}` }));
  async function run(dryRun: boolean) {
    setBusy(true);
    try {
      const r = await api.post<LevelResult>(`/projects/${key}/resources/level`, { plan, dry_run: dryRun });
      if (dryRun) setResult(r);
      else {
        notifications.show({ color: "teal", message: tx("Levelled: {ok} task(s) moved{v}", { ok: r.summary.ok ?? 0, v: r.summary.skipped ? tx(", {skipped} skipped", { skipped: r.summary.skipped }) : "" }) });
        await qc.invalidateQueries({ queryKey: pk(key) });
        onClose();
      }
    } catch (e) {
      notifications.show({ color: "red", message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }
  const overloaded = data.people.filter((p) => p.overloaded).map((p) => p.user.display_name);
  return (
    <Modal opened onClose={onClose} title={tx("Level resources")} size="xl">
      <Stack data-testid="rs-level-modal">
        <Text size="sm" c="dimmed">
          {tx("Tasks of overloaded people move later — never earlier — by working days, keeping their duration and dependencies. Started, frozen and finished work keeps its dates.{v}", { v: overloaded.length ? tx(" Overloaded now: {overloaded}.", { overloaded: overloaded.join(", ") }) : "" })}</Text>
        <Select label={tx("Only work in plan")} placeholder={tx("All tasks")} clearable data={plans} value={plan} onChange={(v) => { setPlan(v); setResult(null); }} />
        {result && <ScheduleTable result={result} />}
        {result && result.remaining_overloads.length > 0 && (
          <Alert color="orange" title={tx("Still overloaded")} data-testid="rs-level-remaining">
            {result.remaining_overloads.map((o) => (
              <Text key={`${o.user?.id}-${o.week}`} size="sm">{tx("{display_name}, week of {week}: {planned} of {capacity} h", { display_name: o.user?.display_name ?? "–", week: short(o.week), planned: fmtH(o.planned), capacity: fmtH(o.capacity) })}</Text>
            ))}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={() => run(true)} loading={busy && !result} data-testid="rs-level-preview">{tx("Preview")}</Button>
          <Button onClick={() => run(false)} disabled={!result || result.moves.length === 0} loading={busy && !!result} data-testid="rs-level-apply">{tx("Apply")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
