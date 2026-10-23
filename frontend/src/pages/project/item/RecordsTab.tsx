import { useState } from "react";
import { Badge, Button, Card, Group, MultiSelect, Select, Table, Text, TextInput, Tooltip } from "@mantine/core";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { useItems, useProjectMutation, useRecords } from "@/api/hooks";
import type { ItemDetail, TestRecord } from "@/api/types";
import { ItemLink } from "@/components/badges";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { ExecuteRecord } from "./ExecuteRecord";

const RESULT_COLORS: Record<string, string> = { passed: "green", failed: "red", blocked: "orange", skipped: "gray", not_run: "gray" };

export function RecordsTab({ item }: { item: ItemDetail }) {
  const { key, model, can } = useProjectCtx();
  const records = useRecords(key, item.key).data ?? [];
  const editable = can("contributor") && !item.lifecycle.frozen;
  const locked = editable ? null : item.lifecycle.frozen
    ? `The run is ${(item.lifecycle.label ?? "frozen").toLowerCase()} — its results are locked.`
    : "Recording results needs the contributor role in this project.";
  const [selected, setSelected] = useState<string[]>([]);
  const testCases = useItems(key, { type: model.config.semantics.test_case_types, limit: 500 }, editable).data?.items ?? [];
  const add = useProjectMutation(key, () => api.post(`/projects/${key}/test-runs/${item.key}/records`, { test_cases: selected }),
    { success: "Test cases added", onSuccess: () => setSelected([]) });
  const existing = new Set(records.map((r) => r.test_case));
  const summary = records.reduce<Record<string, number>>((acc, r) => ({ ...acc, [r.result]: (acc[r.result] ?? 0) + 1 }), {});
  return (
    <>
      <Group mb="md" gap="xs">
        {Object.entries(summary).map(([r, n]) => <Badge key={r} color={RESULT_COLORS[r]} variant="light">{r}: {n}</Badge>)}
      </Group>
      {editable && (
        <Group align="flex-end" mb="md">
          <MultiSelect label="Add test cases" searchable style={{ flex: 1 }} value={selected} onChange={setSelected}
            data={testCases.filter((t) => !existing.has(t.key)).map((t) => ({ value: t.key, label: `${t.key} — ${t.title}` }))} />
          <Button onClick={() => add.mutate(undefined)} disabled={!selected.length} loading={add.isPending}>Add</Button>
        </Group>
      )}
      <Card withBorder padding={0}>
        <Table.ScrollContainer minWidth={760}>
          <Table data-testid="records-table">
            <Table.Thead><Table.Tr><Table.Th>Test case</Table.Th><Table.Th>Result</Table.Th><Table.Th>Comment</Table.Th><Table.Th>Tested version</Table.Th><Table.Th>Executed</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {records.map((r) => <RecordRow key={r.id} rec={r} runKey={item.key} editable={editable} locked={locked} />)}
              {records.length === 0 && <Table.Tr><Table.Td colSpan={6}><Text c="dimmed" ta="center" py="md">No test cases in this run.</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>
    </>
  );
}

function RecordRow({ rec, runKey, editable, locked }: { rec: TestRecord; runKey: string; editable: boolean; locked: string | null }) {
  const { key } = useProjectCtx();
  const [comment, setComment] = useState(rec.comment ?? "");
  const save = useProjectMutation(key, (result: string) => api.patch(`/projects/${key}/test-runs/${runKey}/records/${rec.id}`,
    { result, comment: comment || null }));
  const [executing, setExecuting] = useState(false);
  const failedSteps = rec.step_results.filter((s) => s.result === "failed").length;
  return (
    <Table.Tr data-testid={`record-${rec.test_case}`}>
      <Table.Td><ItemLink item={{ key: rec.test_case, title: rec.title }} withTitle /></Table.Td>
      <Table.Td w={150}>
        {editable ? (
          <Select size="xs" value={rec.result} allowDeselect={false} onChange={(v) => v && save.mutate(v)}
            data={["not_run", "passed", "failed", "blocked", "skipped"]} data-testid="record-result" />
        ) : <Badge color={RESULT_COLORS[rec.result]} variant="light">{rec.result}</Badge>}
      </Table.Td>
      <Table.Td>
        {editable ? <TextInput size="xs" value={comment} onChange={(e) => setComment(e.currentTarget.value)}
          onBlur={() => comment !== (rec.comment ?? "") && save.mutate(rec.result)} /> : <Text size="sm">{rec.comment}</Text>}
      </Table.Td>
      <Table.Td w={130}>
        <Text size="xs" className="mono">rev {rec.tested_version}</Text>
        {rec.outdated && <Tooltip label={`Test case is now ${rec.current_version}`}><Badge size="xs" color="orange">outdated</Badge></Tooltip>}
      </Table.Td>
      <Table.Td w={160}><Text size="xs">{rec.executed_by?.display_name}<br />{fmtDateTime(rec.executed_at)}</Text></Table.Td>
      <Table.Td w={150}>
        <Button size="compact-xs" variant={rec.steps.length ? "light" : "subtle"} onClick={() => setExecuting(true)}
          data-testid={`execute-${rec.test_case}`}>{editable ? "Execute" : "Steps"}{rec.steps.length ? ` (${rec.steps.length})` : ""}</Button>
        {failedSteps > 0 && <Badge size="xs" color="red" ml={4}>{failedSteps} failed</Badge>}
        {rec.defect && <Badge size="xs" color="red" variant="outline" ml={4} component={Link} to={`/p/${key}/items/${rec.defect}`} className="clickable">{rec.defect}</Badge>}
        <ExecuteRecord rec={rec} runKey={runKey} opened={executing} onClose={() => setExecuting(false)} editable={editable} locked={locked} />
      </Table.Td>
    </Table.Tr>
  );
}
