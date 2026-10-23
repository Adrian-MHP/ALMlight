import { useMemo, useState } from "react";
import {
  ActionIcon, Badge, Button, Card, Checkbox, Grid, Group, Modal, MultiSelect, NavLink, NumberInput, Select, SimpleGrid, Stack,
  Text, TextInput, Tooltip,
} from "@mantine/core";
import { IconEdit, IconLayoutKanban, IconPlus, IconTrash } from "@tabler/icons-react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { useBoards, useDirectory, useItems, useProjectMutation } from "@/api/hooks";
import type { Board, BoardConfig, QueryState } from "@/api/types";
import { KanbanBoard } from "@/components/KanbanBoard";
import { PageHeader } from "@/components/PageHeader";
import { QueryBar } from "@/components/QueryBar";
import { queryFields } from "@/lib/queryFields";
import type { Model } from "@/lib/model";
import { useProjectCtx } from "./ProjectLayout";
import { tx } from "@/lib/i18n";

const EMPTY: BoardConfig = { types: [], q: null, conditions: [], columns_by: "state", swimlanes_by: null, hidden_columns: [],
  column_order: [], wip: {}, card_fields: [] };

const TEMPLATES: { name: string; config: Partial<BoardConfig>; needs?: (m: Model) => boolean }[] = [
  { name: tx("Requirements by status"), config: { types: ["system_requirement"], columns_by: "state", swimlanes_by: "field.priority" } },
  { name: tx("Problem reports by owner"), config: { types: ["problem_report"], columns_by: "owner", swimlanes_by: "field.severity" } },
  { name: tx("Tasks by status"), config: { types: ["task"], columns_by: "state", swimlanes_by: "owner" } },
  { name: tx("Risks by level"), config: { types: ["risk"], columns_by: "field.risk_level", swimlanes_by: "state" } },
];

/** Polarion-style boards: saved Kanban views of any item set, grouped by status or any enum/user field. */
export function BoardsPage() {
  const { key, model, can } = useProjectCtx();
  const boards = useBoards(key).data ?? [];
  const [params, setParams] = useSearchParams();
  const current = boards.find((b) => b.id === params.get("board")) ?? boards[0];
  const [editing, setEditing] = useState<Board | "new" | null>(null);
  const [seed, setSeed] = useState<{ name: string; config: BoardConfig } | null>(null);
  const del = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/boards/${id}`), { success: tx("Board deleted"),
    onSuccess: () => setParams({}) });
  const templates = TEMPLATES.filter((t) => (t.config.types ?? []).every((ty) => model.type(ty)));
  return (
    <>
      <PageHeader title={tx("Boards")} subtitle={tx("Kanban boards over any items: move cards to change status, owner, release or a field — the workflow rules apply")}
        actions={<Button leftSection={<IconPlus size={16} />} onClick={() => { setSeed(null); setEditing("new"); }} data-testid="new-board">{tx("New board")}</Button>} />
      <Grid>
        <Grid.Col span={{ base: 12, md: 3, xl: 2 }}>
          <Card withBorder padding="xs">
            {boards.map((b) => (
              <NavLink key={b.id} active={current?.id === b.id} label={b.name} leftSection={<IconLayoutKanban size={16} />}
                description={b.shared ? tx("shared") : tx("personal")} onClick={() => setParams({ board: b.id })} data-testid={`board-${b.name}`} />
            ))}
            {boards.length === 0 && <Text size="sm" c="dimmed" p="xs">{tx("No boards yet.")}</Text>}
          </Card>
          {templates.length > 0 && (
            <Card withBorder padding="xs" mt="sm">
              <Text size="xs" c="dimmed" mb={4}>{tx("Start from a template")}</Text>
              {templates.map((t) => (
                <Button key={t.name} variant="subtle" size="compact-sm" fullWidth justify="flex-start"
                  onClick={() => { setSeed({ name: t.name, config: { ...EMPTY, ...t.config } }); setEditing("new"); }}>{t.name}</Button>
              ))}
            </Card>
          )}
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 9, xl: 10 }}>
          {current ? (
            <Stack gap="xs">
              <Group justify="space-between">
                <Group gap="xs">
                  <Text fw={650} size="lg" data-testid="board-title">{current.name}</Text>
                  {current.shared && <Badge variant="outline" color="gray">{tx("shared")}</Badge>}
                  <Text size="xs" c="dimmed">{describe(model, current.config)}</Text>
                </Group>
                {current.can_edit && (
                  <Group gap={4}>
                    <Tooltip label={tx("Configure")}><ActionIcon variant="subtle" onClick={() => setEditing(current)} data-testid="board-edit" aria-label={tx("Configure board")}><IconEdit size={18} /></ActionIcon></Tooltip>
                    <Tooltip label={tx("Delete")}><ActionIcon variant="subtle" color="red" onClick={() => del.mutate(current.id)} data-testid="board-delete" aria-label={tx("Delete board")}><IconTrash size={18} /></ActionIcon></Tooltip>
                  </Group>
                )}
              </Group>
              <KanbanBoard projectKey={key} model={model} config={current.config} canEdit={can("contributor")} />
            </Stack>
          ) : <Card withBorder p="xl"><Text c="dimmed">{tx("Create a board or start from a template.")}</Text></Card>}
        </Grid.Col>
      </Grid>
      {editing && <BoardModal board={editing === "new" ? null : editing} seed={seed} onClose={() => setEditing(null)}
        onSaved={(b) => setParams({ board: b.id })} />}
    </>
  );
}

function describe(model: Model, c: BoardConfig): string {
  const types = c.types.map((t) => model.typeLabel(t)).join(", ") || tx("all items");
  const by = (g: string | null) => g === "state" ? "status" : g === "release" ? "plan" : g?.startsWith("field.") ? model.config.item_types.flatMap((t) => t.fields).find((f) => f.key === g.slice(6))?.label ?? g : g;
  return tx("{types} · columns by {columns_by}{v}", { types: types, columns_by: by(c.columns_by), v: c.swimlanes_by ? tx(" · swimlanes by {swimlanes_by}", { swimlanes_by: by(c.swimlanes_by) }) : "" });
}

/** Create or configure a board. */
function BoardModal({ board, seed, onClose, onSaved }: { board: Board | null; seed: { name: string; config: BoardConfig } | null; onClose: () => void; onSaved: (b: Board) => void }) {
  const { key, model, can } = useProjectCtx();
  const users = useDirectory().data ?? [];
  const [name, setName] = useState(board?.name ?? seed?.name ?? "");
  const [shared, setShared] = useState(board?.shared ?? false);
  const [cfg, setCfg] = useState<BoardConfig>({ ...EMPTY, ...(board?.config ?? seed?.config ?? {}) });
  const releases = useItems(key, { type: model.releaseType ? [model.releaseType.key] : [], limit: 200 }, !!model.releaseType).data?.items ?? [];
  const fields = useMemo(() => queryFields(model, { users, types: cfg.types, releases: releases.map((r) => ({ value: r.key, label: `${r.key} — ${r.title}` })) }),
    [model, users, cfg.types, releases]);
  const groupFields = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of cfg.types.length ? cfg.types : model.config.item_types.map((x) => x.key)) {
      for (const f of model.type(t)?.fields ?? []) if (["enum", "user", "boolean"].includes(f.type) && !map.has(f.key)) map.set(f.key, f.label);
    }
    return [...map].map(([k, label]) => ({ value: `field.${k}`, label }));
  }, [model, cfg.types]);
  const groupings = [{ value: "state", label: tx("Status") }, { value: "owner", label: tx("Owner") },
    ...(model.releaseType ? [{ value: "release", label: tx("Planned in (release / iteration)") }] : []),
    { value: "type", label: tx("Type") }, ...groupFields];
  const cardFieldOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of cfg.types.length ? cfg.types : model.config.item_types.map((x) => x.key)) {
      for (const f of model.type(t)?.fields ?? []) if (!["text", "steps"].includes(f.type) && !map.has(f.key)) map.set(f.key, f.label);
    }
    return [...map].map(([value, label]) => ({ value, label }));
  }, [model, cfg.types]);
  const columnValues = useMemo(() => {
    if (cfg.columns_by === "state") {
      const m = new Map<string, string>();
      for (const t of cfg.types.length ? cfg.types : model.config.item_types.map((x) => x.key)) for (const s of model.workflow(t)?.states ?? []) m.set(s.key, s.label);
      return [...m].map(([value, label]) => ({ value, label }));
    }
    if (cfg.columns_by.startsWith("field.")) {
      const k = cfg.columns_by.slice(6);
      const def = (cfg.types.length ? cfg.types : model.config.item_types.map((x) => x.key)).map((t) => model.field(t, k)).find(Boolean);
      return (def?.options ?? []).map((o) => ({ value: o.key, label: o.label }));
    }
    return [];
  }, [model, cfg.columns_by, cfg.types]);
  const save = useProjectMutation(key, () => board
    ? api.put<Board>(`/projects/${key}/boards/${board.id}`, { name, shared, config: cfg })
    : api.post<Board>(`/projects/${key}/boards`, { name, shared, config: cfg }),
  { success: board ? tx("Board saved") : tx("Board created"), onSuccess: (b) => { onSaved(b); onClose(); } });
  const query: QueryState = { q: cfg.q ?? "", conditions: cfg.conditions };
  return (
    <Modal opened onClose={onClose} size="xl" title={board ? tx("Configure {name}", { name: board.name }) : tx("New board")}>
      <Stack data-testid="board-modal">
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput label={tx("Name")} value={name} onChange={(e) => setName(e.currentTarget.value)} data-testid="board-name" />
          <MultiSelect label={tx("Item types")} placeholder={tx("All types")} data={model.typeOptions()} value={cfg.types} searchable clearable
            onChange={(v) => setCfg({ ...cfg, types: v })} data-testid="board-types" />
          <Select label={tx("Columns")} data={groupings} value={cfg.columns_by} allowDeselect={false}
            onChange={(v) => setCfg({ ...cfg, columns_by: v ?? "state", hidden_columns: [], column_order: [], wip: {}, swimlanes_by: cfg.swimlanes_by === v ? null : cfg.swimlanes_by })}
            data-testid="board-columns" />
          <Select label={tx("Swimlanes")} placeholder={tx("None")} clearable data={groupings.filter((g) => g.value !== cfg.columns_by)} value={cfg.swimlanes_by}
            onChange={(v) => setCfg({ ...cfg, swimlanes_by: v })} data-testid="board-swimlanes" />
          <MultiSelect label={tx("Fields on cards")} data={cardFieldOptions} value={cfg.card_fields} maxValues={6} clearable
            onChange={(v) => setCfg({ ...cfg, card_fields: v })} data-testid="board-card-fields" />
          {columnValues.length > 0 && (
            <MultiSelect label={tx("Hidden columns")} data={columnValues} value={cfg.hidden_columns} clearable
              onChange={(v) => setCfg({ ...cfg, hidden_columns: v })} />
          )}
        </SimpleGrid>
        <div>
          <Text size="sm" fw={500} mb={4}>{tx("Filter")}</Text>
          <QueryBar projectKey={key} value={query} fields={fields} onChange={(v) => setCfg({ ...cfg, q: v.q || null, conditions: v.conditions })} />
        </div>
        {columnValues.length > 0 && (
          <div>
            <Text size="sm" fw={500} mb={4}>{tx("WIP limits (work in progress per column; empty = none)")}</Text>
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
              {columnValues.filter((c) => !cfg.hidden_columns.includes(c.value)).map((c) => (
                <NumberInput key={c.value} size="xs" label={c.label} min={0} max={999} value={cfg.wip[c.value] ?? ""}
                  onChange={(v) => { const wip = { ...cfg.wip }; if (v === "" || v === 0) delete wip[c.value]; else wip[c.value] = Number(v); setCfg({ ...cfg, wip }); }}
                  data-testid={`wip-${c.value}`} />
              ))}
            </SimpleGrid>
          </div>
        )}
        {can("contributor") && <Checkbox label={tx("Share with the project team")} checked={shared} onChange={(e) => setShared(e.currentTarget.checked)} data-testid="board-shared" />}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!name.trim()} loading={save.isPending} data-testid="board-save">{board ? tx("Save") : tx("Create board")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
