import { useState } from "react";
import { Badge, Button, Card, Grid, Group, Progress, Stack, Table, Text, Tooltip } from "@mantine/core";
import { LineChart } from "@mantine/charts";
import { useElementSize } from "@mantine/hooks";
import { IconPlus } from "@tabler/icons-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { usePlan, usePlans, useProjectMutation } from "@/api/hooks";
import type { PlanSummary } from "@/api/types";
import { ItemPicker } from "@/components/ItemPicker";
import { PageHeader } from "@/components/PageHeader";
import { stateColor } from "@/lib/model";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";

const STATUS: Record<PlanSummary["status"], { color: string; label: string }> = {
  on_track: { color: "green", label: "on track" }, at_risk: { color: "yellow", label: "at risk" },
  overdue: { color: "red", label: "overdue" }, done: { color: "gray", label: "done" },
};

function day(s: string | null): number | null {
  return s ? new Date(`${s}T00:00:00Z`).getTime() : null;
}

/** Month starts between two instants, thinned out so that at most ``fit`` labels are shown (about 60 px each). */
function months(min: number, max: number, fit = 12): { t: number; label: string }[] {
  const out: { t: number; label: string }[] = [];
  const d = new Date(min);
  let cur = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
  while (cur < max) {
    const m = new Date(cur);
    out.push({ t: cur, label: m.toLocaleDateString(undefined, { month: "short", ...(m.getUTCMonth() === 0 ? { year: "numeric" } : {}), timeZone: "UTC" }) });
    cur = Date.UTC(m.getUTCFullYear(), m.getUTCMonth() + 1, 1);
  }
  const step = Math.max(1, Math.ceil(out.length / Math.max(1, fit)));
  return out.filter((_, i) => i % step === 0);
}

/** Releases and milestones on a timeline with progress, schedule status and burn-up. */
export function PlansPage() {
  const { key, model, can } = useProjectCtx();
  const { data } = usePlans(key);
  const [params, setParams] = useSearchParams();
  const selected = params.get("release");
  const [creating, setCreating] = useState(false);
  const axis = useElementSize();
  if (!data) return null;
  if (!data.enabled) {
    return <><PageHeader title="Plans" /><Text c="dimmed">This project's information model has no release type. A manager can take it over from the template (Settings → Information model).</Text></>;
  }
  const dated = data.releases.filter((r) => r.start_date && r.due_date);
  const min = Math.min(...dated.map((r) => day(r.start_date)!), Date.now());
  const max = Math.max(...dated.map((r) => day(r.due_date)!), Date.now() + 86400000);
  const pos = (t: number) => `${((t - min) / (max - min)) * 100}%`;
  return (
    <>
      <PageHeader title="Plans" subtitle="Releases, milestones and iterations: planned requirements, changes and test runs with progress and schedule status"
        actions={can("contributor") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-release">New {data.type_label}</Button>} />
      <Card withBorder mb="md" data-testid="plan-timeline">
        <Text fw={600} mb="sm">Timeline</Text>
        <div className="plan-timeline">
          <div className="plan-axis">
            <span />
            <div className="plan-months" ref={axis.ref}>
              {months(min, max, Math.floor((axis.width || 720) / 60)).map((m) => <span key={m.t} className="plan-month" style={{ left: pos(m.t) }}>{m.label}</span>)}
            </div>
          </div>
          {data.releases.map((r) => {
            const s = day(r.start_date), e = day(r.due_date);
            return (
              <div key={r.key} className="plan-row clickable" onClick={() => setParams({ release: r.key })}>
                <Text size="xs" className="plan-label" truncate><b className="mono">{r.key}</b> {r.title}</Text>
                <div className="plan-track">
                  <div className="plan-today" style={{ left: pos(Date.now()) }} title="Today" />
                  {s && e ? (
                    <Tooltip label={`${r.start_date} → ${r.due_date} · ${Math.round(r.progress * 100)} % done`}>
                      <div className="plan-bar" style={{ left: pos(s), width: `calc(${pos(e)} - ${pos(s)})`, borderColor: `var(--mantine-color-${STATUS[r.status].color}-6)` }}>
                        <div className="plan-fill" style={{ width: `${r.progress * 100}%` }} />
                      </div>
                    </Tooltip>
                  ) : <Text size="xs" c="dimmed">no dates</Text>}
                </div>
              </div>
            );
          })}
        </div>
      </Card>
      <Grid>
        <Grid.Col span={{ base: 12, lg: selected ? 4 : 12 }}>
          <Stack gap="xs">
            {data.releases.map((r) => (
              <Card key={r.key} withBorder padding="sm" className="clickable" onClick={() => setParams({ release: r.key })}
                style={{ borderColor: selected === r.key ? "var(--mantine-primary-color-filled)" : undefined }} data-testid={`release-${r.key}`}>
                <Group justify="space-between" wrap="nowrap" align="flex-start">
                  <Text fw={600} truncate style={{ minWidth: 0 }}><span className="item-key">{r.key}</span> {r.title}</Text>
                  <Badge className="badge-keep" color={STATUS[r.status].color} data-testid={`release-status-${r.key}`}>{STATUS[r.status].label}</Badge>
                </Group>
                <Group gap={6} mt={2} wrap="wrap">
                  <Badge size="xs" variant="light" className="badge-keep" color={stateColor(r.state_color, null)}>{r.state_label}</Badge>
                  <Text size="xs" c="dimmed">{r.start_date ?? "?"} → {r.due_date ?? "?"} · {r.done} of {r.total} done</Text>
                </Group>
                <Progress.Root mt={6} size="lg">
                  <Progress.Section value={r.progress * 100} color="teal"><Progress.Label>{Math.round(r.progress * 100)} %</Progress.Label></Progress.Section>
                </Progress.Root>
                {r.expected != null && <Text size="xs" c="dimmed" mt={2}>Expected by today: {Math.round(r.expected * 100)} %</Text>}
              </Card>
            ))}
            {data.releases.length === 0 && <Text c="dimmed">No releases yet.</Text>}
          </Stack>
        </Grid.Col>
        {selected && <Grid.Col span={{ base: 12, lg: 8 }}><PlanDetailCard releaseKey={selected} plannable={data.plannable_types ?? []} /></Grid.Col>}
      </Grid>
      {model.releaseType && <ItemFormModal opened={creating} onClose={() => setCreating(false)} defaultType={model.releaseType.key} types={[model.releaseType.key]} />}
    </>
  );
}

function PlanDetailCard({ releaseKey, plannable }: { releaseKey: string; plannable: string[] }) {
  const { key, model, can } = useProjectCtx();
  const { data } = usePlan(key, releaseKey);
  const [adding, setAdding] = useState<string | null>(null);
  const add = useProjectMutation(key, () => api.post(`/projects/${key}/links`, { type: model.config.semantics.planned_link, source: adding, target: releaseKey }),
    { success: "Planned into the release", onSuccess: () => setAdding(null) });
  if (!data) return null;
  const today = [...data.burnup].reverse().find((p) => !p.future)?.date.slice(5);
  return (
    <Card withBorder data-testid="plan-detail">
      <Group justify="space-between" mb="xs">
        <div>
          <Text fw={650} size="lg"><Link to={`/p/${key}/items/${data.key}`} className="item-key">{data.key}</Link> {data.title}</Text>
          {data.goal && <Text size="sm" c="dimmed">{data.goal}</Text>}
        </div>
        <Badge size="lg" className="badge-keep" color={STATUS[data.status].color}>{STATUS[data.status].label}</Badge>
      </Group>
      {data.burnup.length > 1 && (
        <LineChart h={220} mb="md" data={data.burnup.map((p) => ({ date: p.date.slice(5), done: p.future ? null : p.done, scope: p.scope }))}
          dataKey="date" series={[{ name: "done", color: "teal.6", label: "Done" }, { name: "scope", color: "gray.5", label: "Scope" }]}
          curveType="stepAfter" withDots={false} connectNulls={false} tickLine="none" gridAxis="y" withLegend legendProps={{ verticalAlign: "top", height: 30 }}
          referenceLines={today ? [{ x: today, label: "Today", color: "red.5" }] : []} data-testid="burnup" />
      )}
      {can("contributor") && (
        <Group align="flex-end" mb="sm">
          <div style={{ flex: 1 }}><ItemPicker label="Plan an item into this release" types={plannable} value={adding} onChange={setAdding} testId="plan-item"
            exclude={[data.key, ...data.items.map((i) => i.key)]} /></div>
          <Button onClick={() => add.mutate(undefined)} disabled={!adding} loading={add.isPending} data-testid="plan-add">Plan</Button>
        </Group>
      )}
      <Table.ScrollContainer minWidth={560}>
        <Table data-testid="plan-items">
          <Table.Thead><Table.Tr><Table.Th>Item</Table.Th><Table.Th>Type</Table.Th><Table.Th>State</Table.Th><Table.Th>Owner</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {data.items.map((i) => (
              <Table.Tr key={i.key}>
                <Table.Td><Link to={`/p/${key}/items/${i.key}`} className="item-key">{i.key}</Link> <Text span size="sm">{i.title}</Text></Table.Td>
                <Table.Td><Text size="sm">{i.type_label}</Text></Table.Td>
                <Table.Td><Badge size="sm" variant={i.done ? "filled" : "light"} color={stateColor(i.state_color, i.state_category)}>{i.state ?? "–"}</Badge></Table.Td>
                <Table.Td><Text size="sm">{i.owner?.display_name}</Text></Table.Td>
              </Table.Tr>
            ))}
            {data.items.length === 0 && <Table.Tr><Table.Td colSpan={4}><Text c="dimmed" ta="center" py="md">Nothing planned yet.</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  );
}
