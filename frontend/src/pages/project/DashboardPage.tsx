import { Anchor, Badge, Card, Group, Progress, RingProgress, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { Link } from "react-router-dom";
import { useAudit, useCoverage, useStats } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { CATEGORY_COLORS, CATEGORY_LABELS } from "@/lib/model";
import { fmtRelative } from "@/lib/format";
import { useProjectCtx } from "./ProjectLayout";

function Kpi({ label, value, to, color }: { label: string; value: number | string; to?: string; color?: string }) {
  const body = (
    <Card withBorder padding="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Text fz={28} fw={700} c={color}>{value}</Text>
    </Card>
  );
  return to ? <Link to={to} style={{ textDecoration: "none", color: "inherit" }}>{body}</Link> : body;
}

function CoverageCard({ type }: { type: string }) {
  const { key, model } = useProjectCtx();
  const { data } = useCoverage(key, type);
  if (!data || data.total === 0) return null;
  return (
    <Card withBorder>
      <Text fw={600} size="sm" mb="xs">{model.typeLabel(type)} <Text span c="dimmed" size="xs">({data.total})</Text></Text>
      <Group gap="lg">
        <RingProgress size={84} thickness={8} roundCaps sections={[{ value: data.verified_pct, color: "green" }]}
          label={<Text ta="center" size="xs" fw={700}>{data.verified_pct}%</Text>} />
        <Stack gap={4} style={{ flex: 1 }}>
          {[["Refined", data.refined_pct, "indigo"], ["Allocated", data.allocated_pct, "grape"], ["With tests", data.with_tests_pct, "teal"],
            ["Verified", data.verified_pct, "green"]].map(([l, v, c]) => (
            <div key={l as string}>
              <Group justify="space-between"><Text size="xs">{l}</Text><Text size="xs">{v}%</Text></Group>
              <Progress value={v as number} color={c as string} size="sm" />
            </div>
          ))}
        </Stack>
      </Group>
    </Card>
  );
}

export function DashboardPage() {
  const { key, project, model } = useProjectCtx();
  const stats = useStats(key).data;
  const audit = useAudit(key).data ?? [];
  const reqTypes = model.typesIn("requirement").map((t) => t.key);
  return (
    <>
      <PageHeader title={project.name} subtitle={project.description ?? undefined} />
      <SimpleGrid cols={{ base: 2, md: 4 }} mb="lg">
        <Kpi label="Items" value={stats?.total_items ?? "–"} to={`/p/${key}/items`} />
        <Kpi label="Open changes" value={stats?.open_changes ?? "–"} to={`/p/${key}/changes`} color={stats?.open_changes ? "orange" : undefined} />
        <Kpi label="Suspect links" value={stats?.suspect_links ?? "–"} to={`/p/${key}/traceability?tab=suspects`} color={stats?.suspect_links ? "orange" : undefined} />
        <Kpi label="Pending approvals" value={stats?.pending_approvals ?? "–"} to="/approvals" color={stats?.pending_approvals ? "indigo" : undefined} />
      </SimpleGrid>
      <Title order={4} mb="sm">Requirement coverage</Title>
      <SimpleGrid cols={{ base: 1, md: 3 }} mb="lg">
        {reqTypes.map((t) => <CoverageCard key={t} type={t} />)}
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder>
          <Title order={5} mb="sm">Items by type and state</Title>
          <Table>
            <Table.Tbody>
              {model.config.item_types.filter((t) => stats?.items_by_type[t.key]).map((t) => {
                const states = stats!.items_by_type[t.key];
                const total = Object.values(states).reduce((a, b) => a + b, 0);
                return (
                  <Table.Tr key={t.key}>
                    <Table.Td>
                      <Anchor component={Link} to={`/p/${key}/items?type=${t.key}`} size="sm">{t.label}</Anchor>
                      <Badge size="xs" ml={6} variant="dot" color={CATEGORY_COLORS[t.category]}>{CATEGORY_LABELS[t.category]}</Badge>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        {Object.entries(states).map(([s, n]) => (
                          <Badge key={s} size="xs" variant="light" color="gray">{s === "-" ? "no lifecycle" : model.state(t.key, s)?.label ?? s}: {n}</Badge>
                        ))}
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right"><Text size="sm" fw={600}>{total}</Text></Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Card>
        <Card withBorder>
          <Group justify="space-between" mb="sm">
            <Title order={5}>Recent activity</Title>
            <Anchor component={Link} to={`/p/${key}/activity`} size="sm">All activity</Anchor>
          </Group>
          <Stack gap={6}>
            {audit.slice(0, 12).map((e) => (
              <Group key={e.id} gap="xs" wrap="nowrap" justify="space-between">
                <Text size="sm" truncate>{e.summary}</Text>
                <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>{e.actor} · {fmtRelative(e.ts)}</Text>
              </Group>
            ))}
          </Stack>
        </Card>
      </SimpleGrid>
    </>
  );
}
