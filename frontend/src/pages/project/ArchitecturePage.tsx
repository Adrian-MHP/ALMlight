import { useState } from "react";
import { Badge, Button, Card, Group, Modal, Select, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { IconPlus, IconSchema } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { pk, useProjectMutation } from "@/api/hooks";
import type { DiagramSummary, ItemDetail } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";
import { tx } from "@/lib/i18n";
import { useProjectCtx } from "./ProjectLayout";

export const VIEWPOINTS = [
  { value: "context", label: tx("System context") },
  { value: "decomposition", label: tx("Decomposition") },
  { value: "internal", label: tx("Internal structure and interfaces") },
  { value: "allocation", label: tx("Requirements allocation") },
  { value: "deployment", label: tx("Physical / deployment") },
  { value: "free", label: tx("Free") },
];

export function viewpointLabel(key: string | undefined): string {
  return VIEWPOINTS.find((v) => v.value === key)?.label ?? tx("Free");
}

/** The architecture diagrams of the project: views of its elements, functions, interfaces and requirements. */
export function ArchitecturePage() {
  const { key, can, model } = useProjectCtx();
  const [creating, setCreating] = useState(false);
  const diagrams = useQuery<DiagramSummary[]>({
    queryKey: pk(key, "diagrams"), queryFn: () => api.get(`/projects/${key}/diagrams`),
  }).data;
  if (!model.type("diagram")) {
    return (
      <>
        <PageHeader title={tx("Architecture")} />
        <Text c="dimmed">{tx("This project's information model has no diagram type. A manager adds it under Settings → Information model (take over the template additions).")}</Text>
      </>
    );
  }
  return (
    <>
      <PageHeader title={tx("Architecture")}
        subtitle={tx("Views of the model: elements, functions, interfaces and their relationships. A diagram shows items of this project — what you draw here is a real link.")}
        actions={can("contributor") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="diagram-new">{tx("New diagram")}</Button>} />
      {diagrams?.length === 0 && (
        <Card withBorder p="xl">
          <Stack align="center" gap="xs">
            <IconSchema size={36} />
            <Text fw={600}>{tx("No diagram yet.")}</Text>
            <Text size="sm" c="dimmed" ta="center" maw={620}>
              {tx("A diagram is a view of this project's model: put elements on the canvas, draw relationships that become real links, and arrange them. The elements stay items — removing one from a diagram does not delete it.")}
            </Text>
          </Stack>
        </Card>
      )}
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {diagrams?.map((d) => (
          <Card key={d.key} withBorder component={Link} to={`/p/${key}/architecture/${d.key}`} className="clickable"
            data-testid={`diagram-${d.key}`}>
            <Group justify="space-between" wrap="nowrap" mb={4}>
              <Text fw={600} lineClamp={1}>{d.title}</Text>
              <Badge size="xs" variant="light" style={{ flexShrink: 0 }}>{d.key}</Badge>
            </Group>
            <Text size="xs" c="dimmed">{viewpointLabel(d.viewpoint)}</Text>
            <Group gap="xs" mt="sm">
              <Badge size="xs" variant="outline">{tx("{n} elements", { n: d.nodes })}</Badge>
              <Badge size="xs" variant="outline">{tx("{n} relationships", { n: d.edges })}</Badge>
              <Text size="xs" c="dimmed" ml="auto">{fmtRelative(d.updated_at)}</Text>
            </Group>
          </Card>
        ))}
      </SimpleGrid>
      {creating && <NewDiagram onClose={() => setCreating(false)} />}
    </>
  );
}

function NewDiagram({ onClose }: { onClose: () => void }) {
  const { key } = useProjectCtx();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [viewpoint, setViewpoint] = useState<string | null>("internal");
  const create = useProjectMutation(key, () => api.post<ItemDetail>(`/projects/${key}/items`,
    { type: "diagram", title, fields: { viewpoint } }), {
    success: tx("Diagram created"),
    onSuccess: (d) => { onClose(); navigate(`/p/${key}/architecture/${d.key}`); },
  });
  return (
    <Modal opened onClose={onClose} title={tx("New diagram")}>
      <Stack>
        <TextInput label={tx("Title")} value={title} onChange={(e) => setTitle(e.currentTarget.value)} required
          data-testid="diagram-title" autoFocus placeholder={tx("e.g. Sensor system — internal structure")} />
        <Select label={tx("Viewpoint")} data={VIEWPOINTS} value={viewpoint} onChange={setViewpoint} allowDeselect={false}
          data-testid="diagram-viewpoint"
          description={tx("Suggests which element and relationship types belong on this diagram. It does not restrict them.")} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button onClick={() => create.mutate(undefined)} disabled={!title.trim()} loading={create.isPending}
            data-testid="diagram-create">{tx("Create")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
