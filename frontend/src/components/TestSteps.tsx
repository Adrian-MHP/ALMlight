import { ActionIcon, Button, Group, Table, Text, Textarea, Tooltip } from "@mantine/core";
import { IconArrowDown, IconArrowUp, IconPlus, IconTrash } from "@tabler/icons-react";
import type { TestStep } from "@/api/types";

/** Editable table of test steps (action + expected result). */
export function StepsEditor({ value, onChange, label = "Test steps" }: {
  value: TestStep[] | null | undefined; onChange: (v: TestStep[]) => void; label?: string;
}) {
  const steps = value ?? [];
  const set = (i: number, patch: Partial<TestStep>) => onChange(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, d: number) => {
    const next = [...steps];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    onChange(next);
  };
  return (
    <div data-testid="steps-editor">
      <Text size="sm" fw={500} mb={4}>{label}</Text>
      <Table withTableBorder verticalSpacing={4}>
        <Table.Thead><Table.Tr><Table.Th w={36}>#</Table.Th><Table.Th>Action</Table.Th><Table.Th>Expected result</Table.Th><Table.Th w={92} /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {steps.map((s, i) => (
            <Table.Tr key={i}>
              <Table.Td><Text size="sm" c="dimmed">{i + 1}</Text></Table.Td>
              <Table.Td><Textarea autosize minRows={1} size="xs" value={s.step} onChange={(e) => set(i, { step: e.currentTarget.value })} data-testid={`step-action-${i + 1}`} /></Table.Td>
              <Table.Td><Textarea autosize minRows={1} size="xs" value={s.expected} onChange={(e) => set(i, { expected: e.currentTarget.value })} data-testid={`step-expected-${i + 1}`} /></Table.Td>
              <Table.Td>
                <Group gap={2} wrap="nowrap">
                  <ActionIcon size="sm" variant="subtle" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up"><IconArrowUp size={14} /></ActionIcon>
                  <ActionIcon size="sm" variant="subtle" disabled={i === steps.length - 1} onClick={() => move(i, 1)} aria-label="Move down"><IconArrowDown size={14} /></ActionIcon>
                  <Tooltip label="Remove step"><ActionIcon size="sm" variant="subtle" color="red" onClick={() => onChange(steps.filter((_, j) => j !== i))}><IconTrash size={14} /></ActionIcon></Tooltip>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Button size="xs" variant="light" mt={6} leftSection={<IconPlus size={14} />} onClick={() => onChange([...steps, { step: "", expected: "" }])}
        data-testid="add-step">Add step</Button>
    </div>
  );
}

/** Read-only numbered steps. */
export function StepsView({ steps }: { steps: TestStep[] }) {
  if (!steps.length) return <Text size="sm" c="dimmed">No steps defined.</Text>;
  return (
    <Table withTableBorder verticalSpacing={4} data-testid="steps-view">
      <Table.Thead><Table.Tr><Table.Th w={36}>#</Table.Th><Table.Th>Action</Table.Th><Table.Th>Expected result</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>
        {steps.map((s, i) => (
          <Table.Tr key={i}><Table.Td>{i + 1}</Table.Td><Table.Td style={{ whiteSpace: "pre-wrap" }}>{s.step}</Table.Td>
            <Table.Td style={{ whiteSpace: "pre-wrap" }}>{s.expected}</Table.Td></Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
