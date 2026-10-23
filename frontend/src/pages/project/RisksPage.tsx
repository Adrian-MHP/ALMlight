import { useState } from "react";
import { Badge, Button, Card, Grid, Group, SegmentedControl, SimpleGrid, Table, Text, Tooltip } from "@mantine/core";
import { IconPlus, IconShieldCheck } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { useRisks } from "@/api/hooks";
import type { RiskRow } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { stateColor } from "@/lib/model";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";

const LEVEL_COLOR: Record<string, string> = { high: "red", medium: "yellow", low: "green" };
const LEVEL_RANK: Record<string, number> = { low: 1, medium: 2, high: 3 };

/** Background of a heat-map cell: severity × occurrence (detection is assumed medium for the map). */
function cellColor(s: number, o: number): string {
  const score = s * o;
  if (score >= 40) return "var(--mantine-color-red-light)";
  if (score >= 16) return "var(--mantine-color-yellow-light)";
  return "var(--mantine-color-green-light)";
}

/** Risk management (FMEA): matrix before/after mitigation, register sorted by RPN, mitigation coverage. */
export function RisksPage() {
  const { key, model, can } = useProjectCtx();
  const { data } = useRisks(key);
  const [view, setView] = useState<"before" | "after">("before");
  const [cell, setCell] = useState<{ s: number; o: number } | null>(null);
  const [creating, setCreating] = useState(false);
  if (!data) return null;
  if (!data.enabled) {
    return <><PageHeader title="Risks" /><Text c="dimmed">This project's information model has no risk type. A manager can take it over from the template (Settings → Information model).</Text></>;
  }
  const scale = data.scale ?? 10;
  const matrix = (view === "before" ? data.matrix : data.residual_matrix) ?? [];
  const s = data.summary!;
  const sevKey = view === "before" ? "severity" : "severity_after";
  const occKey = view === "before" ? "occurrence" : "occurrence_after";
  const rows = (data.risks ?? []).filter((r) => !cell || (r[sevKey as keyof RiskRow] === cell.s && r[occKey as keyof RiskRow] === cell.o));
  // the worst rated level (RPN incl. detection) of the risks in each cell colours its count
  const levelKey = view === "before" ? "level" : "residual_level";
  const worst: Record<string, string> = {};
  for (const r of data.risks ?? []) {
    const lv = r[levelKey as keyof RiskRow] as string | null;
    const at = `${r[sevKey as keyof RiskRow]}-${r[occKey as keyof RiskRow]}`;
    if (lv && (LEVEL_RANK[lv] ?? 0) > (LEVEL_RANK[worst[at]] ?? 0)) worst[at] = lv;
  }
  return (
    <>
      <PageHeader title="Risks" subtitle="Failure modes and hazards rated by severity, occurrence and detection (FMEA); mitigated by requirements, design and tests"
        actions={can("contributor") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-risk">New {data.type_label}</Button>} />
      <SimpleGrid cols={{ base: 2, md: 5 }} mb="md">
        {[["Risks", s.total, "gray"], ["High", s.high, "red"], ["High without mitigation", s.high_unmitigated, s.high_unmitigated ? "red" : "green"],
          ["High residual risk", s.residual_high, s.residual_high ? "red" : "green"], ["Accepted", s.accepted, "green"]].map(([label, value, color]) => (
          <Card key={label as string} withBorder padding="sm" data-testid={`risk-kpi-${label}`}>
            <Text size="xs" tt="uppercase" fw={600} c="dimmed">{label}</Text>
            <Text fz={26} fw={650} c={value ? (color as string) : undefined}>{value}</Text>
          </Card>
        ))}
      </SimpleGrid>
      <Grid>
        <Grid.Col span={{ base: 12, lg: 5 }}>
          <Card withBorder>
            <Group justify="space-between" mb="sm">
              <Text fw={600}>Risk matrix</Text>
              <SegmentedControl size="xs" value={view} onChange={(v) => { setView(v as "before" | "after"); setCell(null); }}
                data={[{ value: "before", label: "Initial" }, { value: "after", label: "After mitigation" }]} data-testid="risk-view" />
            </Group>
            <div className="risk-matrix" data-testid="risk-matrix">
              <div className="risk-axis-y">Severity →</div>
              <table>
                <tbody>
                  {Array.from({ length: scale }, (_, i) => scale - i).map((sev) => (
                    <tr key={sev}>
                      <th>{sev}</th>
                      {Array.from({ length: scale }, (_, j) => j + 1).map((occ) => {
                        const n = matrix[sev - 1]?.[occ - 1] ?? 0;
                        const active = cell && cell.s === sev && cell.o === occ;
                        return (
                          <td key={occ} style={{ background: cellColor(sev, occ), outline: active ? "2px solid var(--mantine-primary-color-filled)" : undefined }}
                            className={n ? "clickable" : undefined} onClick={() => n && setCell(active ? null : { s: sev, o: occ })}
                            data-testid={n ? `risk-cell-${sev}-${occ}` : undefined}>
                            {n ? <span className="risk-count" style={{ background: `var(--mantine-color-${LEVEL_COLOR[worst[`${sev}-${occ}`]] ?? "gray"}-6)` }}>{n}</span> : ""}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  <tr><th />{Array.from({ length: scale }, (_, j) => <th key={j}>{j + 1}</th>)}</tr>
                </tbody>
              </table>
              <div className="risk-axis-x">Occurrence →</div>
            </div>
            {cell && <Button size="compact-xs" variant="subtle" mt="xs" onClick={() => setCell(null)}>Show all (filtered: S{cell.s} × O{cell.o})</Button>}
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 7 }}>
          <Card withBorder padding={0}>
            <Table.ScrollContainer minWidth={640}>
              <Table data-testid="risk-register" highlightOnHover>
                <Table.Thead><Table.Tr><Table.Th>Risk</Table.Th><Table.Th>S</Table.Th><Table.Th>O</Table.Th><Table.Th>D</Table.Th><Table.Th>RPN</Table.Th><Table.Th>Mitigation</Table.Th><Table.Th>Residual</Table.Th><Table.Th>State</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {rows.map((r) => (
                    <Table.Tr key={r.key} data-testid={`risk-${r.key}`}>
                      <Table.Td>
                        <Link to={`/p/${key}/items/${r.key}`} className="item-key">{r.key}</Link> <Text span size="sm">{r.title}</Text>
                        {r.failure_mode && <Text size="xs" c="dimmed">{r.failure_mode}</Text>}
                      </Table.Td>
                      <Table.Td>{r.severity ?? "–"}</Table.Td><Table.Td>{r.occurrence ?? "–"}</Table.Td><Table.Td>{r.detection ?? "–"}</Table.Td>
                      <Table.Td>{r.rpn != null ? <Badge color={LEVEL_COLOR[r.level ?? ""] ?? "gray"} variant="light">{r.rpn}</Badge> : "–"}</Table.Td>
                      <Table.Td>
                        {r.mitigations ? <Badge leftSection={<IconShieldCheck size={11} />} color="teal" variant="light">{r.mitigations}</Badge>
                          : r.level === "high" ? <Tooltip label="High risk without mitigation"><Badge color="red">none</Badge></Tooltip> : <Text size="xs" c="dimmed">none</Text>}
                      </Table.Td>
                      <Table.Td>{r.rpn_after != null ? <Badge color={LEVEL_COLOR[r.residual_level ?? ""] ?? "gray"} variant="outline">{r.rpn_after}</Badge> : "–"}</Table.Td>
                      <Table.Td><Badge size="sm" variant="light" color={stateColor(r.state_color, r.state_category)}>{r.state_label}</Badge></Table.Td>
                    </Table.Tr>
                  ))}
                  {rows.length === 0 && <Table.Tr><Table.Td colSpan={8}><Text c="dimmed" ta="center" py="md">No risks{cell ? " in this cell" : " yet"}.</Text></Table.Td></Table.Tr>}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        </Grid.Col>
      </Grid>
      {model.riskType && <ItemFormModal opened={creating} onClose={() => setCreating(false)} defaultType={model.riskType.key} types={[model.riskType.key]} />}
    </>
  );
}
