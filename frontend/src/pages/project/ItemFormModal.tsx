import { useEffect, useState } from "react";
import { Alert, Button, Group, Input, Modal, Select, Stack, Text, TextInput } from "@mantine/core";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useProjectMutation } from "@/api/hooks";
import type { ItemDetail } from "@/api/types";
import { FieldsForm } from "@/components/FieldsForm";
import { ItemPicker } from "@/components/ItemPicker";
import { HtmlEditor } from "@/components/rich/HtmlEditor";
import { useProjectCtx } from "./ProjectLayout";
import { tx } from "@/lib/i18n";

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
        title: title !== item.title ? title : undefined, fields: changedFields, applicability,
        expected_version: item.version_no, change_note: note || null,
      });
    }
    return api.post<ItemDetail>(`/projects/${key}/items`, {
      type, title, description, fields: Object.fromEntries(Object.entries(fields).filter(([, v]) => v !== null && v !== "" && v !== undefined)),
      applicability: applicability || null, parent, position,
    });
  }, {
    success: (r) => (item ? tx("Saved {key} ({version})", { key: r.key, version: r.version }) : tx("Created {key}", { key: r.key })),
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
    <Modal opened={opened} onClose={onClose} size="xl" title={item ? tx("Properties of {key}", { key: item.key }) : tx("New item")}>
      <Stack>
        {!item && (
          <Select label={tx("Type")} placeholder={tx("Choose an item type")} data={model.typeOptions((t) => !types || types.includes(t.key))}
            value={type} onChange={(v) => { setType(v); setFields({}); }} searchable required data-testid="item-type" />
        )}
        {typeDef?.description && <Text size="xs" c="dimmed">{typeDef.description}</Text>}
        <TextInput label={tx("Title")} value={title} onChange={(e) => setTitle(e.currentTarget.value)} required data-autofocus
          data-testid="item-title" />
        {!item ? (
          <Input.Wrapper label={tx("Text")} description={tx("Rich text: formatting, lists, tables, images (paste or upload), # references an item")}>
            <div style={{ marginTop: 6 }}>
              <HtmlEditor value={description} onChange={setDescription} projectKey={key} testId="item-description" minHeight={120} />
            </div>
          </Input.Wrapper>
        ) : (
          <Text size="xs" c="dimmed">{tx("The text is edited live (together with others) on the item page and in documents.")}</Text>
        )}
        {typeDef && <FieldsForm defs={typeDef.fields} values={fields} onChange={(k, v) => setFields((f) => ({ ...f, [k]: v }))} />}
        <TextInput label={tx("Applicability (variants)")} description={tx("Feature expression, e.g. OUT_HART and not EX — empty = all variants")}
          value={applicability} onChange={(e) => { setApplicability(e.currentTarget.value); setExprCheck(null); }} onBlur={checkExpression}
          className="mono" data-testid="item-applicability"
          error={exprCheck && !exprCheck.valid ? exprCheck.error : undefined} />
        {exprCheck?.valid && exprCheck.unknown.length > 0 && (
          <Alert color="yellow" py={6}>{tx("Unknown feature codes: {unknown}", { unknown: exprCheck.unknown.join(", ") })}</Alert>
        )}
        {!item && parentTypes.length > 0 && (
          <ItemPicker label={tx("Place under (optional)")} types={parentTypes} value={parent} onChange={setParent}
            description={tx("Adds the item to a document, structure or feature tree")} />
        )}
        {item && <TextInput label={tx("Change note (optional)")} value={note} onChange={(e) => setNote(e.currentTarget.value)} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button onClick={() => save.mutate(undefined)} loading={save.isPending} disabled={!type || !title.trim()} data-testid="item-save">
            {item ? tx("Save") : tx("Create")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
