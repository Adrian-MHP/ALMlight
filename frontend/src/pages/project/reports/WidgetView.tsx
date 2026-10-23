import { BarChart, DonutChart, LineChart } from "@mantine/charts";
import { Alert, Badge, Group, Progress, SimpleGrid, Stack, Table, Text, Tooltip } from "@mantine/core";
import { Link } from "react-router-dom";
import type { ReportWidget, WidgetData } from "@/api/types";
import { Markdown } from "@/components/Markdown";
import { fmtDate } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { tx } from "@/lib/i18n";

export const PALETTE = ["indigo.6", "teal.6", "orange.6", "grape.6", "cyan.6", "pink.6", "lime.7", "yellow.6", "red.6", "blue.6",
  "violet.6", "gray.6"];

const SERIES_LABELS: Record<string, string> = { created: tx("Created"), released: tx("Released / approved"), changed: tx("Changed") };

/** Renders the evaluated data of one report widget. */
export function WidgetView({ widget, data }: { widget: ReportWidget; data: WidgetData | undefined }) {
  if (!data) return <Text c="dimmed" size="sm">{tx("Loading…")}</Text>;
  if (!data.ok) return <Alert color="red" variant="light">{data.error}</Alert>;
  switch (widget.type) {
    case "markdown": return <Markdown text={data.text} empty={tx("(empty text block)")} />;
    case "kpi": return <KpiValue data={data} />;
    case "chart": return <ChartView widget={widget} data={data} />;
    case "table": return <TableView data={data} />;
    case "trend": return <TrendView data={data} />;
    case "coverage": return <CoverageView data={data} />;
    case "matrix": return <MatrixView data={data} />;
    case "maturity": return <MaturityView data={data} />;
    case "reuse": return <ReuseView data={data} />;
    case "change_lead_time": return <LeadTimeView data={data} />;
    case "retest_effort": return <RetestView data={data} />;
    case "variant_ratio": return <RatioView data={data} />;
    default: return null;
  }
}

function Tile({ label, value, unit, color, hint }: { label: string; value: unknown; unit?: string; color?: string; hint?: string }) {
  return (
    <div>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Tooltip label={hint} disabled={!hint}>
        <Text fz={24} fw={700} c={color} lh={1.2}>{value === null || value === undefined ? "–" : String(value)}{unit}</Text>
      </Tooltip>
    </div>
  );
}

function KpiValue({ data }: { data: WidgetData }) {
  const color = data.status === "good" ? "teal" : data.status === "bad" ? "red" : undefined;
  return (
    <Stack gap={4}>
      <Text fz={40} fw={700} c={color} lh={1} data-testid="kpi-value">{data.value}{data.unit}</Text>
      {data.unit === "%" && <Text size="xs" c="dimmed">{tx("{numerator} of {denominator} items", { numerator: data.numerator, denominator: data.denominator })}</Text>}
      {data.target !== null && data.target !== undefined && <Text size="xs" c="dimmed">{tx("Target {target}{unit}", { target: data.target, unit: data.unit })}</Text>}
    </Stack>
  );
}

function ItemKey({ k }: { k: string }) {
  const { key } = useProjectCtx();
  return <Link to={`/p/${key}/items/${k}`} className="item-key">{k}</Link>;
}

function ChartView({ widget, data }: { widget: ReportWidget; data: WidgetData }) {
  const groups = data.groups as { key: string; label: string; total: number; series: Record<string, number> }[];
  const stacks = data.stacks as { key: string; label: string }[];
  if (!groups.length) return <Text c="dimmed" size="sm">{tx("No items match.")}</Text>;
  if (widget.chart === "donut" || widget.chart === "pie") {
    const cells = groups.map((g, i) => ({ name: g.label, value: g.total, color: PALETTE[i % PALETTE.length] }));
    return (
      <Group align="center" wrap="nowrap" gap="lg">
        <DonutChart data={cells} thickness={widget.chart === "pie" ? 80 : 22} size={170} withTooltip />
        <Stack gap={4}>
          {cells.map((c) => (
            <Group key={c.name} gap={6} wrap="nowrap">
              <span style={{ width: 10, height: 10, borderRadius: 2, background: `var(--mantine-color-${c.color.replace(".", "-")})` }} />
              <Text size="sm">{c.name}</Text>
              <Text size="sm" c="dimmed">{c.value}</Text>
            </Group>
          ))}
        </Stack>
      </Group>
    );
  }
  const rows = groups.map((g) => ({ label: g.label, ...(stacks.length ? g.series : { total: g.total }) }));
  const series = stacks.length
    ? stacks.map((s, i) => ({ name: s.key, label: s.label, color: PALETTE[i % PALETTE.length] }))
    : [{ name: "total", label: tx("Items"), color: "indigo.6" }];
  return (
    <BarChart h={Math.max(200, widget.chart === "horizontal" ? groups.length * 34 + 40 : 240)} data={rows} dataKey="label"
      series={series} type={stacks.length ? "stacked" : "default"} orientation={widget.chart === "horizontal" ? "vertical" : "horizontal"}
      withLegend={stacks.length > 0} tickLine="y" gridAxis="y" />
  );
}

function TableView({ data }: { data: WidgetData }) {
  const columns = data.columns as string[];
  const rows = data.rows as Record<string, string>[];
  const label = (c: string) => (c.startsWith("field:") ? c.slice(6) : c).replace(/_/g, " ");
  return (
    <>
      <Table.ScrollContainer minWidth={400}>
        <Table striped>
          <Table.Thead><Table.Tr>{columns.map((c) => <Table.Th key={c} tt="capitalize">{label(c)}</Table.Th>)}</Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r, i) => (
              <Table.Tr key={i}>
                {columns.map((c) => (
                  <Table.Td key={c}>
                    {c === "key" ? <ItemKey k={r[c]} /> : <Text size="sm">{c === "updated" ? fmtDate(r[c]) : r[c] ?? ""}</Text>}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {data.total > rows.length && <Text size="xs" c="dimmed" mt={4}>{tx("Showing {length} of {total}", { length: rows.length, total: data.total })}</Text>}
      {data.total === 0 && <Text size="sm" c="dimmed">{tx("No items match.")}</Text>}
    </>
  );
}

function TrendView({ data }: { data: WidgetData }) {
  const periods = data.periods as string[];
  const series = data.series as Record<string, number[]>;
  const names = Object.keys(series);
  const rows = periods.map((p, i) => ({ period: p.slice(5), ...Object.fromEntries(names.map((n) => [n, series[n][i]])) }));
  return (
    <LineChart h={240} data={rows} dataKey="period" withLegend curveType="linear"
      series={names.map((n, i) => ({ name: n, label: SERIES_LABELS[n] ?? n, color: PALETTE[i] }))} />
  );
}

function CoverageView({ data }: { data: WidgetData }) {
  const bars: [string, number, string][] = [[tx("Refined"), data.refined_pct, "indigo"], [tx("Allocated"), data.allocated_pct, "grape"],
    [tx("With tests"), data.with_tests_pct, "teal"], [tx("Verified"), data.verified_pct, "green"]];
  return (
    <Stack gap="xs">
      <Text size="sm">{tx("{label}: {total} items", { label: data.label, total: data.total })}</Text>
      {bars.map(([l, v, c]) => (
        <div key={l}>
          <Group justify="space-between"><Text size="xs">{l}</Text><Text size="xs">{v}%</Text></Group>
          <Progress value={v} color={c} size="sm" />
        </div>
      ))}
      {(data.gaps as { key: string; title: string; verification: string }[]).length > 0 && (
        <>
          <Text size="xs" c="dimmed" mt={4}>{tx("Not yet verified")}</Text>
          {(data.gaps as { key: string; title: string; verification: string }[]).slice(0, 8).map((g) => (
            <Group key={g.key} gap={6} wrap="nowrap"><ItemKey k={g.key} /><Text size="xs" truncate>{g.title}</Text>
              <Badge size="xs" variant="light" color="gray">{g.verification}</Badge></Group>
          ))}
        </>
      )}
    </Stack>
  );
}

function MatrixView({ data }: { data: WidgetData }) {
  const rows = data.rows as { id: string; key: string; title: string }[];
  const cols = data.cols as { id: string; key: string; title: string }[];
  const cells = new Map((data.cells as { row: string; col: string; suspect: boolean }[]).map((c) => [`${c.row}|${c.col}`, c]));
  return (
    <>
      <Text size="xs" c="dimmed" mb={4}>{tx("{rows_covered_pct}% of rows have at least one link", { rows_covered_pct: data.rows_covered_pct })}</Text>
      <Table.ScrollContainer minWidth={300}>
        <Table withColumnBorders>
          <Table.Thead><Table.Tr><Table.Th />{cols.map((c) => <Table.Th key={c.id} className="matrix-cell"><Tooltip label={c.title}><span className="item-key" style={{ writingMode: "vertical-rl" }}>{c.key}</span></Tooltip></Table.Th>)}</Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td style={{ whiteSpace: "nowrap" }}><ItemKey k={r.key} /></Table.Td>
                {cols.map((c) => {
                  const cell = cells.get(`${r.id}|${c.id}`);
                  return <Table.Td key={c.id} className="matrix-cell" bg={cell ? (cell.suspect ? "var(--mantine-color-orange-light)" : "var(--mantine-color-indigo-light)") : undefined}>{cell ? "●" : ""}</Table.Td>;
                })}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </>
  );
}

function MaturityView({ data }: { data: WidgetData }) {
  const done = data.done as Record<string, number>;
  return (
    <SimpleGrid cols={4}>
      {["specified", "realised", "verified", "validated"].map((k) => (
        <div key={k}>
          <Text size="xs" c="dimmed" tt="uppercase">{k}</Text>
          <Text fw={700} fz={20}>{done[k]} / {data.total}</Text>
          <Progress value={data.total ? (100 * done[k]) / data.total : 0} size="sm" color="teal" />
        </div>
      ))}
    </SimpleGrid>
  );
}

function ReuseView({ data }: { data: WidgetData }) {
  const strategies = Object.entries(data.by_strategy as Record<string, number>);
  const rows = (data.rows as { key: string; title: string; level: string | null; reuse_strategy: string | null; products: number }[])
    .filter((r) => r.level === "module" || r.level === "component");
  return (
    <Stack gap="sm">
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Tile label={tx("Modules")} value={data.modules} />
        <Tile label={tx("Reuse rate")} value={data.reuse_rate_pct} unit="%" hint={tx("Modules/components with strategy reused, standard or purchased")} />
        <Tile label={tx("Used in ≥ 2 products")} value={data.multi_use_pct} unit="%" />
        <Tile label={tx("Products per module")} value={data.avg_products_per_module} />
      </SimpleGrid>
      {strategies.length > 0 && (
        <Group gap={6}>{strategies.map(([s, n], i) => <Badge key={s} variant="light" color={PALETTE[i % PALETTE.length].split(".")[0]}>{s}: {n}</Badge>)}</Group>
      )}
      <Table>
        <Table.Thead><Table.Tr><Table.Th>{tx("Module")}</Table.Th><Table.Th>{tx("Level")}</Table.Th><Table.Th>{tx("Strategy")}</Table.Th><Table.Th ta="right">{tx("Products")}</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows.slice(0, 12).map((r) => (
            <Table.Tr key={r.key}><Table.Td><Group gap={6} wrap="nowrap"><ItemKey k={r.key} /><Text size="sm" truncate>{r.title}</Text></Group></Table.Td>
              <Table.Td><Text size="sm">{r.level}</Text></Table.Td><Table.Td><Text size="sm">{r.reuse_strategy ?? "–"}</Text></Table.Td>
              <Table.Td ta="right"><Text size="sm" fw={600}>{r.products}</Text></Table.Td></Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function LeadTimeView({ data }: { data: WidgetData }) {
  const types = Object.entries(data.types as Record<string, { label: string; count: number; open: number;
    lead_days: { avg: number | null; median: number | null; p90: number | null }; open_age_days: { avg: number | null } }>);
  const trend = data.trend as { period: string; finished: number; avg_lead_days: number }[];
  const open = (data.rows as { key: string; title: string; state: string; open_age_days: number | null }[])
    .filter((r) => r.open_age_days !== null).sort((a, b) => (b.open_age_days ?? 0) - (a.open_age_days ?? 0)).slice(0, 6);
  if (!types.length) return <Text c="dimmed" size="sm">{tx("No change items yet.")}</Text>;
  return (
    <Stack gap="sm">
      <Table>
        <Table.Thead><Table.Tr><Table.Th>{tx("Type")}</Table.Th><Table.Th ta="right">{tx("Total")}</Table.Th><Table.Th ta="right">{tx("Open")}</Table.Th>
          <Table.Th ta="right">{tx("Avg lead (d)")}</Table.Th><Table.Th ta="right">{tx("Median")}</Table.Th><Table.Th ta="right">P90</Table.Th><Table.Th ta="right">{tx("Open age (d)")}</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>
          {types.map(([k, t]) => (
            <Table.Tr key={k}><Table.Td>{t.label}</Table.Td><Table.Td ta="right">{t.count}</Table.Td><Table.Td ta="right">{t.open}</Table.Td>
              <Table.Td ta="right" fw={600}>{t.lead_days.avg ?? "–"}</Table.Td><Table.Td ta="right">{t.lead_days.median ?? "–"}</Table.Td>
              <Table.Td ta="right">{t.lead_days.p90 ?? "–"}</Table.Td><Table.Td ta="right">{t.open_age_days.avg ?? "–"}</Table.Td></Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {data.end_to_end?.avg !== null && data.end_to_end?.avg !== undefined && (
        <Text size="sm">{tx("End-to-end (change request → change order released):")} <b>{tx("{avg} days", { avg: data.end_to_end.avg })}</b> {tx("on average")}</Text>
      )}
      {trend.length > 1 && (
        <LineChart h={180} data={trend} dataKey="period" series={[{ name: "avg_lead_days", label: tx("Avg lead time (days)"), color: "orange.6" }]} />
      )}
      {open.length > 0 && (
        <Stack gap={2}>
          <Text size="xs" c="dimmed">{tx("Oldest open changes")}</Text>
          {open.map((r) => <Group key={r.key} gap={6} wrap="nowrap"><ItemKey k={r.key} /><Text size="xs" truncate>{r.title}</Text>
            <Badge size="xs" variant="light">{r.state}</Badge><Text size="xs" c="dimmed">{r.open_age_days} d</Text></Group>)}
        </Stack>
      )}
    </Stack>
  );
}

function RetestView({ data }: { data: WidgetData }) {
  const overall = data.overall;
  const variants = data.variants as { variant: string; title: string; applicable: number; passed_current: number; needs_retest: number;
    never_run: number; failed: number; estimated_minutes: number; retest_pct: number }[];
  return (
    <Stack gap="sm">
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Tile label={tx("Test cases")} value={overall.applicable} />
        <Tile label={tx("Current & passed")} value={overall.passed_current} color="teal" />
        <Tile label={tx("Need (re-)test")} value={overall.needs_retest} color={overall.needs_retest ? "orange" : undefined} />
        <Tile label={tx("Est. effort")} value={overall.estimated_minutes} unit={tx(" min")} hint={tx("Sum of the last known durations")} />
      </SimpleGrid>
      {variants.length > 0 && (
        <>
          <BarChart h={Math.max(160, variants.length * 36 + 40)} data={variants.map((v) => ({ label: v.variant, passed: v.passed_current, retest: v.needs_retest }))}
            dataKey="label" type="stacked" orientation="vertical" withLegend
            series={[{ name: "passed", label: tx("Current & passed"), color: "teal.6" }, { name: "retest", label: tx("Needs (re-)test"), color: "orange.6" }]} />
          <Table>
            <Table.Thead><Table.Tr><Table.Th>{tx("Variant")}</Table.Th><Table.Th ta="right">{tx("Applicable")}</Table.Th><Table.Th ta="right">{tx("Re-test")}</Table.Th>
              <Table.Th ta="right">{tx("Failed")}</Table.Th><Table.Th ta="right">{tx("Never run")}</Table.Th><Table.Th ta="right">{tx("Effort (min)")}</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {variants.map((v) => (
                <Table.Tr key={v.variant}><Table.Td><Group gap={6} wrap="nowrap"><ItemKey k={v.variant} /><Text size="sm" truncate>{v.title}</Text></Group></Table.Td>
                  <Table.Td ta="right">{v.applicable}</Table.Td><Table.Td ta="right" fw={600}>{v.needs_retest} ({v.retest_pct}%)</Table.Td>
                  <Table.Td ta="right">{v.failed}</Table.Td><Table.Td ta="right">{v.never_run}</Table.Td><Table.Td ta="right">{v.estimated_minutes}</Table.Td></Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </>
      )}
    </Stack>
  );
}

function RatioView({ data }: { data: WidgetData }) {
  const rows = data.rows as { variant: string; title: string; modules: number; variant_specific_modules: number; valid: boolean }[];
  return (
    <Stack gap="sm">
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Tile label={tx("Offered variants")} value={data.offered_variants} />
        <Tile label={tx("Modules")} value={data.modules_total} hint={tx("{modules_common} common, {modules_variant_specific} variant-specific", { modules_common: data.modules_common, modules_variant_specific: data.modules_variant_specific })} />
        <Tile label={tx("Modules / variant")} value={data.modules_per_variant_ratio} />
        <Tile label={tx("Variant-specific / variant")} value={data.variant_specific_per_variant} />
      </SimpleGrid>
      <Table>
        <Table.Thead><Table.Tr><Table.Th>{tx("Variant")}</Table.Th><Table.Th ta="right">{tx("Modules used")}</Table.Th><Table.Th ta="right">{tx("Variant-specific")}</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows.map((r) => (
            <Table.Tr key={r.variant}><Table.Td><Group gap={6} wrap="nowrap"><ItemKey k={r.variant} /><Text size="sm" truncate>{r.title}</Text></Group></Table.Td>
              <Table.Td ta="right">{r.modules}</Table.Td><Table.Td ta="right">{r.variant_specific_modules}</Table.Td>
              <Table.Td>{!r.valid && <Badge size="xs" color="red">{tx("invalid")}</Badge>}</Table.Td></Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
