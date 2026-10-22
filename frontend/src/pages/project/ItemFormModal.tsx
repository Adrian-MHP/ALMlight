import { useEffect, useState } from "react";
import { Alert, Button, Group, Modal, Select, Stack, Tabs, Text, Textarea, TextInput } from "@mantine/core";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useProjectMutation } from "@/api/hooks";
import type { ItemDetail } from "@/api/types";
import { FieldsForm } from "@/components/FieldsForm";
import { ItemPicker } from "@/components/ItemPicker";
import { Markdown } from "@/components/Markdown";
import { useProjectCtx } from "./ProjectLayout";

interface Props {
  opened: boolean;
  onClose: () => void;
  /** Edit this item; otherwise create a new one. */
  item?: ItemDetail;
  defaultType?: string;
  types?: string[];
  parent?: string | null;
  position?: number | null;
  navigateOnCreate?: boolean;
  onSaved?: (item: ItemDetail) => void;
}

export function ItemFormModal({ opened, onClose, item, defaultType, types, parent: initialParent, position, navigateOnCreate = true, onSaved }: Props) {
  const { key, model } = useProjectCtx();
  const navigate = useNavigate();
  const [type, setType] = useState<string | null>(item?.type_key ?? defaultType ?? null);
  const [title, setTitle] = useState(item?.title ?? "");
  const [description, setDescription] = useState(item?.description ?? "");
  const [fields, setFields] = useState<Record<string, unknown>>(item?.fields ?? {});
  const [applicability, setApplicability] = useState(item?.applicability ?? "");
  const [parent, setParent] = useState<string | null>(initialParent ?? null);
  const [note, setNote] = useState("");
  const [exprCheck, setExprCheck] = useState<{ valid: boolean; error: string | null; unknown: string[] } | null>(null);

  useEffect(() => {
    if (!opened) return;
    setType(item?.type_key ?? defaultType ?? null);
    setTitle(item?.title ?? "");
    setDescription(item?.description ?? "");
    setFields(item?.fields ?? {});
    setApplicability(item?.applicability ?? "");
    setParent(initialParent ?? null);
    setNote("");
    setExprCheck(null);
  }, [opened, item, defaultType, initialParent]);

  const typeDef = type ? model.type(type) : undefined;
  const save = useProjectMutation(key, async () => {
    if (item) {
      const changedFields: Record<string, unknown> = {};
      for (const f of typeDef?.fields ?? []) {
        const before = item.fields[f.key] ?? null;
        const after = fields[f.key] ?? null;
        if (JSON.stringify(before) !== JSON.stringify(after)) changedFields[f.key] = after;
      }
      return api.patch<ItemDetail>(`/projects/${key}/items/${item.key}`, {
        title, description, fields: changedFields, applicability, expected_version: item.version_no, change_note: note || null,
      });
    }
    return api.post<ItemDetail>(`/projects/${key}/items`, {
      type, title, description, fields: Object.fromEntries(Object.entries(fields).filter(([, v]) => v !== null && v !== "" && v !== undefined)),
      applicability: applicability || null, parent, position,
    });
  }, {
    success: (r) => (item ? `Saved ${r.key} (${r.version})` : `Created ${r.key}`),
    onSuccess: (r) => {
      onClose();
      onSaved?.(r);
      if (!item && navigateOnCreate) navigate(`/p/${key}/items/${r.key}`);
    },
  });

  async function checkExpression() {
    if (!applicability.trim()) { setExprCheck(null); return; }
    setExprCheck(await api.post(`/projects/${key}/variants/check-expression`, { expression: applicability }));
  }

  const parentTypes = type ? model.config.item_types.filter((t) =>
    model.config.link_types.some((lt) => lt.structural && (lt.sources.includes(t.key)) && (lt.targets.includes(type) || lt.targets.includes("*")))).map((t) => t.key) : [];

  return (
    <Modal opened={opened} onClose={onClose} size="xl" title={item ? `Edit ${item.key}` : "New item"}>
      <Stack>
        {!item && (
          <Select label="Type" placeholder="Choose an item type" data={model.typeOptions((t) => !types || types.includes(t.key))}
            value={type} onChange={(v) => { setType(v); setFields({}); }} searchable required data-testid="item-type" />
        )}
        {typeDef?.description && <Text size="xs" c="dimmed">{typeDef.description}</Text>}
        <TextInput label="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} required data-autofocus
          data-testid="item-title" />
        <Tabs defaultValue="write">
          <Tabs.List>
            <Tabs.Tab value="write">Description</Tabs.Tab>
            <Tabs.Tab value="preview">Preview</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="write" pt="xs">
            <Textarea autosize minRows={4} maxRows={14} value={description} placeholder="Markdown supported"
              onChange={(e) => setDescription(e.currentTarget.value)} data-testid="item-description" />
          </Tabs.Panel>
          <Tabs.Panel value="preview" pt="xs"><Markdown text={description} /></Tabs.Panel>
        </Tabs>
        {typeDef && <FieldsForm defs={typeDef.fields} values={fields} onChange={(k, v) => setFields((f) => ({ ...f, [k]: v }))} />}
        <TextInput label="Applicability (variants)" description="Feature expression, e.g. OUT_HART and not EX — empty = all variants"
          value={applicability} onChange={(e) => { setApplicability(e.currentTarget.value); setExprCheck(null); }} onBlur={checkExpression}
          className="mono" data-testid="item-applicability"
          error={exprCheck && !exprCheck.valid ? exprCheck.error : undefined} />
        {exprCheck?.valid && exprCheck.unknown.length > 0 && (
          <Alert color="yellow" py={6}>Unknown feature codes: {exprCheck.unknown.join(", ")}</Alert>
        )}
        {!item && parentTypes.length > 0 && (
          <ItemPicker label="Place under (optional)" types={parentTypes} value={parent} onChange={setParent}
            description="Adds the item to a document, structure or feature tree" />
        )}
        {item && <TextInput label="Change note (optional)" value={note} onChange={(e) => setNote(e.currentTarget.value)} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} loading={save.isPending} disabled={!type || !title.trim()} data-testid="item-save">
            {item ? "Save" : "Create"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
