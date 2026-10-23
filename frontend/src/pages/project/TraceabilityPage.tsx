import { useState } from "react";
import { ActionIcon, Badge, Card, Group, Progress, Select, SimpleGrid, Table, Tabs, Text, Tooltip } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { useCoverage, useFeatureModel, useProjectMutation, useSuspects, useTraceMatrix } from "@/api/hooks";
import { ItemLink, VerificationBadge } from "@/components/badges";
import { PageHeader } from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";
import { useProjectCtx } from "./ProjectLayout";
import { tm, tx } from "@/lib/i18n";

export function TraceabilityPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "coverage";
  return (
    <>
      <PageHeader title={tx("Traceability")} subtitle={tx("Coverage from needs to verification, traceability matrices and links to review")} />
      <Tabs value={tab} onChange={(v) => setParams({ tab: v ?? "coverage" })}>
        <Tabs.List mb="md">
          <Tabs.Tab value="coverage">{tx("Coverage")}</Tabs.Tab>
          <Tabs.Tab value="matrix">{tx("Matrix")}</Tabs.Tab>
          <Tabs.Tab value="suspects" data-testid="tab-suspects">{tx("Suspect links")}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="coverage"><CoverageView /></Tabs.Panel>
        <Tabs.Panel value="matrix"><MatrixView /></Tabs.Panel>
        <Tabs.Panel value="suspects"><SuspectsView /></Tabs.Panel>
      </Tabs>
    </>
  );
}

function CoverageView() {
  const { key, model } = useProjectCtx();
  const reqTypes = model.typesIn("requirement");
  const [type, setType] = useState<string | null>(reqTypes.find((t) => t.key.includes("system"))?.key ?? reqTypes[0]?.key ?? null);
  const [variant, setVariant] = useState<string | null>(null);
  const variants = useFeatureModel(key).data?.variants ?? [];
  const { data } = useCoverage(key, type, variant);
  return (
    <>
      <Group mb="md">
        <Select label={tx("Requirement type")} data={reqTypes.map((t) => ({ value: t.key, label: t.label }))} value={type} onChange={setType} allowDeselect={false} />
        <Select label={tx("Verification for variant")} placeholder={tx("any variant")} clearable value={variant} onChange={setVariant}
          data={variants.map((v) => ({ value: v.key, label: `${v.key} — ${v.title}` }))} />
      </Group>
      {data && (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
            {[[tx("Refined / derived"), data.refined_pct, "indigo"], [tx("Allocated"), data.allocated_pct, "grape"], [tx("Has tests"), data.with_tests_pct, "teal"], [tx("Verified"), data.verified_pct, "green"]].map(([l, v, c]) => (
              <Card withBorder key={l as string} padding="sm">
                <Group justify="space-between"><Text size="sm">{l}</Text><Text fw={700}>{v}%</Text></Group>
                <Progress value={v as number} color={c as string} mt={6} />
              </Card>
            ))}
          </SimpleGrid>
          <Card withBorder padding={0}>
            <Table data-testid="coverage-table">
              <Table.Thead>
                <Table.Tr><Table.Th>{tx("Requirement")}</Table.Th><Table.Th>{tx("State")}</Table.Th><Table.Th ta="center">{tx("Refined by")}</Table.Th>
                  <Table.Th ta="center">{tx("Allocated to")}</Table.Th><Table.Th ta="center">{tx("Tests")}</Table.Th><Table.Th>{tx("Verification")}</Table.Th><Table.Th /></Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.rows.map((r) => (
                  <Table.Tr key={r.id}>
                    <Table.Td><ItemLink item={r} withTitle /></Table.Td>
                    <Table.Td><Text size="sm">{tm(r.state_label)}</Text></Table.Td>
                    <Table.Td ta="center"><Count n={r.refined_by} /></Table.Td>
                    <Table.Td ta="center"><Count n={r.satisfied_by} /></Table.Td>
                    <Table.Td ta="center"><Count n={r.verified_by} /></Table.Td>
                    <Table.Td><VerificationBadge status={r.verification} /></Table.Td>
                    <Table.Td>{r.suspect_links > 0 && <Badge color="orange" size="sm">{tx("{suspect_links} suspect", { suspect_links: r.suspect_links })}</Badge>}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        </>
      )}
    </>
  );
}

function Count({ n }: { n: number }) {
  return n ? <Badge variant="light" color="indigo">{n}</Badge> : <Text size="sm" c="red">–</Text>;
}

function MatrixView() {
  const { key, model } = useProjectCtx();
  const types = model.config.item_types.filter((t) => !t.document && t.category !== "variability").map((t) => ({ value: t.key, label: t.label }));
  const [rows, setRows] = useState<string | null>(model.type("system_requirement") ? "system_requirement" : types[0]?.value ?? null);
  const [cols, setCols] = useState<string | null>(model.type("test_case") ? "test_case" : types[1]?.value ?? null);
  const { data } = useTraceMatrix(key, rows, cols);
  const cells = new Map((data?.cells ?? []).map((c) => [`${c.row}|${c.col}`, c]));
  return (
    <>
      <Group mb="md">
        <Select label={tx("Rows")} data={types} value={rows} onChange={setRows} searchable />
        <Select label={tx("Columns")} data={types} value={cols} onChange={setCols} searchable />
      </Group>
      {data && (
        <Card withBorder padding={0}>
          <Table.ScrollContainer minWidth={400}>
            <Table withColumnBorders data-testid="trace-matrix">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th />
                  {data.cols.map((c) => (
                    <Table.Th key={c.id} className="matrix-cell">
                      <Tooltip label={c.title}><Link to={`/p/${key}/items/${c.key}`} className="item-key" style={{ writingMode: "vertical-rl" }}>{c.key}</Link></Tooltip>
                    </Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.rows.map((r) => (
                  <Table.Tr key={r.id}>
                    <Table.Td style={{ whiteSpace: "nowrap" }}><ItemLink item={r} withTitle /></Table.Td>
                    {data.cols.map((c) => {
                      const cell = cells.get(`${r.id}|${c.id}`);
                      return (
                        <Table.Td key={c.id} className="matrix-cell" bg={cell ? (cell.suspect ? "var(--mantine-color-orange-light)" : "var(--mantine-color-indigo-light)") : undefined}>
                          {cell && <Tooltip label={`${model.link(cell.type)?.label ?? cell.type}${cell.suspect ? " (suspect)" : ""}`}><Text size="xs">●</Text></Tooltip>}
                        </Table.Td>
                      );
                    })}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Card>
      )}
    </>
  );
}

function SuspectsView() {
  const { key, model, can } = useProjectCtx();
  const suspects = useSuspects(key).data ?? [];
  const confirm = useProjectMutation(key, (id: string) => api.post(`/projects/${key}/links/${id}/confirm`, {}), { success: tx("Link confirmed") });
  if (!suspects.length) return <Text c="dimmed">{tx("No suspect links — all traces are up to date.")}</Text>;
  return (
    <Card withBorder padding={0}>
      <Table data-testid="suspects-table">
        <Table.Thead><Table.Tr><Table.Th>{tx("Dependent item")}</Table.Th><Table.Th>{tx("Relation")}</Table.Th><Table.Th>{tx("Changed item")}</Table.Th><Table.Th>{tx("Reason")}</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {suspects.map((s) => (
            <Table.Tr key={s.link_id}>
              <Table.Td><ItemLink item={{ key: s.source, title: s.source_title }} withTitle /></Table.Td>
              <Table.Td><Text size="sm">{model.link(s.type)?.label ?? s.type}</Text></Table.Td>
              <Table.Td><ItemLink item={{ key: s.target, title: s.target_title }} withTitle /></Table.Td>
              <Table.Td><Text size="xs">{s.reason} · {fmtRelative(s.since)}</Text></Table.Td>
              <Table.Td w={50}>
                {can("contributor") && <Tooltip label={tx("Reviewed — still valid")}><ActionIcon color="green" variant="subtle" onClick={() => confirm.mutate(s.link_id)}><IconCheck size={16} /></ActionIcon></Tooltip>}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}
