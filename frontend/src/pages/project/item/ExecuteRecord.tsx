import { useEffect, useState } from "react";
import { Alert, Badge, Button, Drawer, Group, SegmentedControl, Stack, Table, Text, Textarea, TextInput } from "@mantine/core";
import { IconBug, IconCheck, IconLock } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { useProjectMutation } from "@/api/hooks";
import type { TestRecord } from "@/api/types";
import { useProjectCtx } from "../ProjectLayout";

const RESULTS = [
  { value: "passed", label: "Pass" }, { value: "failed", label: "Fail" }, { value: "blocked", label: "Blocked" },
  { value: "skipped", label: "Skip" }, { value: "not_run", label: "–" },
];
const COLORS: Record<string, string> = { passed: "green", failed: "red", blocked: "orange", skipped: "gray", not_run: "gray" };

/** Step-by-step execution of one test case in a run: result and actual outcome per step, defect from a failed step. */
export function ExecuteRecord({ rec, runKey, opened, onClose, editable, locked }: {
  rec: TestRecord; runKey: string; opened: boolean; onClose: () => void; editable: boolean; locked?: string | null;
}) {
  const { key } = useProjectCtx();
  const [steps, setSteps] = useState(rec.step_results.length ? rec.step_results : rec.steps.map(() => ({ result: "not_run", actual: "", comment: "" })));
  const [comment, setComment] = useState(rec.comment ?? "");
  useEffect(() => {
    setSteps(rec.step_results.length ? rec.step_results : rec.steps.map(() => ({ result: "not_run", actual: "", comment: "" })));
    setComment(rec.comment ?? "");
  }, [rec]);
  const store = () => api.patch<TestRecord[]>(`/projects/${key}/test-runs/${runKey}/records/${rec.id}`, {
    step_results: steps, comment: comment || null,
  });
  const save = useProjectMutation(key, store, { success: (r) => `Saved — ${r.find((x) => x.id === rec.id)?.result ?? ""}` });
  // the defect quotes the step's expected and actual outcome, so the entered results are stored first
  const defect = useProjectMutation(key, async (step: number) => {
    await store();
    return api.post<{ defect: string }>(`/projects/${key}/test-runs/${runKey}/records/${rec.id}/defect`, { step });
  }, { success: (r) => `Defect ${r.defect} created` });
  const set = (i: number, patch: Partial<(typeof steps)[number]>) => setSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  return (
    <Drawer opened={opened} onClose={onClose} position="right" size="xl"
      title={<Group gap="xs"><Text fw={600}>Execute {rec.test_case}</Text><Text c="dimmed">{rec.title}</Text></Group>}>
      <Stack data-testid="execute-drawer">
        <Group gap="xs">
          <Badge color={COLORS[rec.result]} variant="light">Current result: {rec.result}</Badge>
          {rec.defect && <Badge color="red" variant="outline" component={Link} to={`/p/${key}/items/${rec.defect}`} className="clickable">Defect {rec.defect}</Badge>}
        </Group>
        {!editable && locked && <Alert color="gray" icon={<IconLock size={16} />} py={6} data-testid="execute-locked">{locked}</Alert>}
        {!rec.steps.length && <Alert color="yellow">This test case has no structured steps — set the overall result in the run table.</Alert>}
        {rec.steps.length > 0 && (
          <Table.ScrollContainer minWidth={620}>
            <Table withTableBorder verticalSpacing={6}>
              <Table.Thead><Table.Tr><Table.Th w={30}>#</Table.Th><Table.Th>Action / expected</Table.Th><Table.Th w={editable ? 250 : 110}>Result</Table.Th><Table.Th>Actual</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rec.steps.map((st, i) => (
                  <Table.Tr key={i} data-testid={`exec-step-${i + 1}`}>
                    <Table.Td>{i + 1}</Table.Td>
                    <Table.Td>
                      <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{st.step}</Text>
                      {st.expected && <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-wrap" }}>Expected: {st.expected}</Text>}
                    </Table.Td>
                    <Table.Td>
                      {editable ? (
                        <SegmentedControl size="xs" fullWidth value={steps[i]?.result ?? "not_run"}
                          onChange={(v) => set(i, { result: v })} data={RESULTS} color={COLORS[steps[i]?.result ?? "not_run"]} />
                      ) : <Badge variant="light" color={COLORS[steps[i]?.result ?? "not_run"]}>{RESULTS.find((r) => r.value === (steps[i]?.result ?? "not_run"))?.label === "–" ? "not run" : steps[i]?.result}</Badge>}
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        {editable ? <TextInput size="xs" style={{ flex: 1 }} value={steps[i]?.actual ?? ""}
                          onChange={(e) => set(i, { actual: e.currentTarget.value })} placeholder="Observed outcome" />
                          : <Text size="sm" style={{ flex: 1, whiteSpace: "pre-wrap" }} c={steps[i]?.actual ? undefined : "dimmed"}>{steps[i]?.actual || "–"}</Text>}
                        {editable && steps[i]?.result === "failed" && !rec.defect && (
                          <Button size="compact-xs" color="red" variant="light" leftSection={<IconBug size={12} />}
                            loading={defect.isPending} onClick={() => defect.mutate(i + 1)} data-testid={`defect-step-${i + 1}`}>Defect</Button>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {editable ? <Textarea label="Comment" autosize minRows={2} value={comment} onChange={(e) => setComment(e.currentTarget.value)} />
          : comment && <div><Text size="sm" fw={500}>Comment</Text><Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{comment}</Text></div>}
        {editable && (
          <Group justify="flex-end">
            <Text size="xs" c="dimmed">The overall result follows the steps: any failed → failed, all passed → passed.</Text>
            <Button leftSection={<IconCheck size={16} />} onClick={() => save.mutate(undefined)} loading={save.isPending} data-testid="execute-save">Save results</Button>
          </Group>
        )}
      </Stack>
    </Drawer>
  );
}
