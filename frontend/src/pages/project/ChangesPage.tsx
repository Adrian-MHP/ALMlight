import { useState } from "react";
import { Button, SegmentedControl, Text } from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { KanbanBoard } from "@/components/KanbanBoard";
import { PageHeader } from "@/components/PageHeader";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";

/** Change management board: problem reports, change requests and change orders by lifecycle state (drag to move). */
export function ChangesPage() {
  const { key, model, can } = useProjectCtx();
  const changeTypes = model.typesIn("change");
  const [type, setType] = useState<string>(changeTypes.find((t) => t.key === "change_request")?.key ?? changeTypes[0]?.key ?? "");
  const [creating, setCreating] = useState(false);
  if (!changeTypes.length) return <Text c="dimmed">This project's information model has no change item types.</Text>;
  return (
    <>
      <PageHeader title="Changes" subtitle="Closed-loop change management: problem report → change request (impact analysis, CCB decision) → change order (implementation, release)"
        actions={can("contributor") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-change">New {model.typeLabel(type)}</Button>} />
      <SegmentedControl mb="md" value={type} onChange={setType} data={changeTypes.map((t) => ({ value: t.key, label: t.label }))} />
      <KanbanBoard key={type} projectKey={key} model={model} canEdit={can("contributor")} testId="changes-board"
        config={{ types: [type], conditions: [], columns_by: "state", swimlanes_by: null, hidden_columns: [], column_order: [], wip: {},
          card_fields: model.type(type)?.fields.some((f) => f.key === "priority") ? ["priority"] : model.type(type)?.fields.some((f) => f.key === "severity") ? ["severity"] : [] }} />
      <ItemFormModal opened={creating} onClose={() => setCreating(false)} defaultType={type} types={changeTypes.map((t) => t.key)} />
    </>
  );
}
