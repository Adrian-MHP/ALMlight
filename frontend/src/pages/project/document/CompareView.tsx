import { useMemo, useState } from "react";
import { Alert, Anchor, Badge, Breadcrumbs, Card, Center, Chip, Grid, Group, Loader, MultiSelect, Stack, Text, Title } from "@mantine/core";
import { IconArrowsMove } from "@tabler/icons-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useCompare } from "@/api/hooks";
import type { CompareResult, DocStateRef } from "@/api/types";
import { RichDiff, RichText } from "@/components/rich/RichText";
import { useProjectCtx } from "../ProjectLayout";
import { tx } from "@/lib/i18n";

const STATUS = {
  added: { color: "green", label: tx("added") },
  removed: { color: "red", label: tx("removed") },
  changed: { color: "orange", label: tx("changed") },
  moved: { color: "blue", label: tx("moved") },
  unchanged: { color: "gray", label: tx("unchanged") },
} as const;

type Row = CompareResult["rows"][number];

function DiffText({ diff, side }: { diff: { op: string; text: string }[]; side: "left" | "right" }) {
  return (
    <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
      {diff.map((d, i) => {
        if (d.op === "equal") return <span key={i}>{d.text}</span>;
        if (d.op === "delete" && side === "left") return <span key={i} className="diff-del" style={{ textDecoration: "line-through" }}>{d.text}</span>;
        if (d.op === "insert" && side === "right") return <span key={i} className="diff-add">{d.text}</span>;
        return null;
      })}
    </Text>
  );
}

function Side({ row, side }: { row: Row; side: "left" | "right" }) {
  const { key } = useProjectCtx();
  const node = row[side];
  if (!node) return <Text size="sm" c="dimmed" fs="italic">{side === "left" ? tx("— not present —") : tx("— removed —")}</Text>;
  const titleDiff = row.changes.find((c) => c.field === "title")?.diff;
  const descHtml = row.changes.find((c) => c.field === "description")?.html_diff;
  return (
    <Stack gap={4}>
      <Group gap={6}>
        <Link to={`/p/${key}/items/${node.key}`} className="item-key">{node.key}</Link>
        {node.is_heading ? (
          <Text fw={700}>{node.number ? `${node.number} ` : ""}{titleDiff ? <DiffText diff={titleDiff} side={side} /> : node.title}</Text>
        ) : (
          <Text fw={600} size="sm" component="div">{titleDiff ? <DiffText diff={titleDiff} side={side} /> : node.title}</Text>
        )}
        {node.state && <Badge size="xs" variant="light" color="gray">{node.state}</Badge>}
        <Text size="xs" c="dimmed" className="mono">{node.version}</Text>
      </Group>
      {!node.is_heading && (descHtml ? <RichDiff html={descHtml} side={side === "left" ? "old" : "new"} />
        : <RichText html={node.description} empty="" />)}
    </Stack>
  );
}

/** Side-by-side comparison of two document states (revision, baseline, branch or another document). */
export function CompareView() {
  const { specKey = "" } = useParams();
  const docKey = specKey.toUpperCase();
  const { key, model } = useProjectCtx();
  const [params] = useSearchParams();
  const left: DocStateRef = { document: params.get("l_doc") ?? docKey, at: params.get("l_at"), baseline: params.get("l_bl") };
  const right: DocStateRef = { document: params.get("r_doc") ?? docKey, project: params.get("r_proj"), at: params.get("r_at"), baseline: params.get("r_bl") };
  const [fields, setFields] = useState<string[]>([]);
  const { data, isLoading, error } = useCompare(key, left, right, fields);
  const [show, setShow] = useState<string[]>(["added", "removed", "changed", "moved"]);
  const fieldOptions = useMemo(() => {
    const m = new Map<string, string>();
    model.config.item_types.forEach((t) => t.fields.forEach((f) => m.set(f.key, f.label)));
    return [...m].map(([value, label]) => ({ value, label }));
  }, [model]);
  const rows = (data?.rows ?? []).filter((r) => show.includes(r.status) || (r.moved && show.includes("moved")));

  return (
    <>
      <Breadcrumbs mb="xs" separator="›">
        <Anchor component={Link} to={`/p/${key}/documents`} size="sm">{tx("Documents")}</Anchor>
        <Anchor component={Link} to={`/p/${key}/documents/${docKey}`} size="sm" className="item-key">{docKey}</Anchor>
        <Text size="sm">{tx("Compare")}</Text>
      </Breadcrumbs>
      <Title order={2} size="h3" mb="sm">{tx("Compare documents")}</Title>
      {isLoading && <Center mt="xl"><Loader /></Center>}
      {error && <Alert color="red">{error.message}</Alert>}
      {data && (
        <Stack data-testid="compare-view">
          <Grid>
            <Grid.Col span={6}><Card withBorder padding="sm" bg="var(--mantine-color-red-light)">
              <Text size="xs" c="dimmed">{tx("Left")}</Text>
              <Text fw={600}>{data.left.project}/{data.left.document} — {data.left.title}</Text>
              <Text size="sm">{data.left.source}</Text>
            </Card></Grid.Col>
            <Grid.Col span={6}><Card withBorder padding="sm" bg="var(--mantine-color-green-light)">
              <Text size="xs" c="dimmed">{tx("Right")}</Text>
              <Text fw={600}>{data.right.project}/{data.right.document} — {data.right.title}</Text>
              <Text size="sm">{data.right.source}</Text>
            </Card></Grid.Col>
          </Grid>
          <Group justify="space-between" wrap="wrap">
            <Chip.Group multiple value={show} onChange={setShow}>
              <Group gap="xs">
                {(Object.keys(STATUS) as (keyof typeof STATUS)[]).map((s) => (
                  <Chip key={s} value={s} size="xs" color={STATUS[s].color} data-testid={`chip-${s}`}>{STATUS[s].label} ({data.summary[s]})</Chip>
                ))}
              </Group>
            </Chip.Group>
            <MultiSelect size="xs" w={320} placeholder={tx("Compare all fields")} data={fieldOptions} value={fields} onChange={setFields} clearable
              label={tx("Fields to compare")} />
          </Group>
          {rows.length === 0 && <Text c="dimmed">{tx("No differences in the selected categories.")}</Text>}
          {rows.map((r, i) => (
            <Card key={i} withBorder padding="sm" data-testid={`cmp-${(r.right ?? r.left)!.key}`}>
              <Group gap={6} mb={6}>
                <Badge color={STATUS[r.status].color} variant="light">{STATUS[r.status].label}</Badge>
                {r.moved && r.status !== "moved" && <Badge color="blue" variant="light" leftSection={<IconArrowsMove size={10} />}>{tx("moved")}</Badge>}
                {r.changes.filter((c) => !["title", "description"].includes(c.field)).map((c) => (
                  <Badge key={c.field} size="sm" variant="outline" color="gray" style={{ textTransform: "none" }}>
                    {c.field.replace("fields.", "")}: {String(c.old ?? "∅")} → {String(c.new ?? "∅")}
                  </Badge>
                ))}
              </Group>
              <Grid>
                <Grid.Col span={6}><Side row={r} side="left" /></Grid.Col>
                <Grid.Col span={6}><Side row={r} side="right" /></Grid.Col>
              </Grid>
            </Card>
          ))}
        </Stack>
      )}
    </>
  );
}
