import { Checkbox, MultiSelect, NumberInput, Select, SimpleGrid, TagsInput, Text, Textarea, TextInput } from "@mantine/core";
import type { FieldDef } from "@/api/types";
import { useDirectory } from "@/api/hooks";
import { fmtValue } from "@/lib/format";

/** Form inputs generated from the configured field definitions of an item type. */
export function FieldsForm({ defs, values, onChange }: {
  defs: FieldDef[];
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  const users = useDirectory().data ?? [];
  if (!defs.length) return null;
  const wide = defs.filter((f) => f.type === "text");
  const narrow = defs.filter((f) => f.type !== "text");
  return (
    <>
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
        {narrow.map((f) => <FieldInput key={f.key} def={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} users={users} />)}
      </SimpleGrid>
      {wide.map((f) => <FieldInput key={f.key} def={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} users={users} />)}
    </>
  );
}

function FieldInput({ def, value, onChange, users }: {
  def: FieldDef; value: unknown; onChange: (v: unknown) => void; users: { id: string; display_name: string }[];
}) {
  const common = { label: def.label, description: def.help ?? undefined, required: def.required, "data-testid": `field-${def.key}` };
  switch (def.type) {
    case "text":
      return <Textarea {...common} autosize minRows={2} maxRows={10} value={(value as string) ?? ""} onChange={(e) => onChange(e.currentTarget.value)} />;
    case "integer":
    case "number":
      return <NumberInput {...common} value={(value as number) ?? ""} allowDecimal={def.type === "number"}
        onChange={(v) => onChange(v === "" ? null : v)} />;
    case "boolean":
      return <Checkbox {...common} mt="lg" checked={!!value} onChange={(e) => onChange(e.currentTarget.checked)} />;
    case "date":
      return <TextInput {...common} type="date" value={(value as string) ?? ""} onChange={(e) => onChange(e.currentTarget.value || null)} />;
    case "enum":
      return <Select {...common} clearable data={def.options.map((o) => ({ value: o.key, label: o.label }))}
        value={(value as string) ?? null} onChange={(v) => onChange(v)} />;
    case "multienum":
      return <MultiSelect {...common} data={def.options.map((o) => ({ value: o.key, label: o.label }))}
        value={(value as string[]) ?? []} onChange={(v) => onChange(v)} />;
    case "tags":
      return <TagsInput {...common} value={(value as string[]) ?? []} onChange={(v) => onChange(v)} />;
    case "user":
      return <Select {...common} clearable searchable data={users.map((u) => ({ value: u.id, label: u.display_name }))}
        value={(value as string) ?? null} onChange={(v) => onChange(v)} />;
    default:
      return <TextInput {...common} value={(value as string) ?? ""} onChange={(e) => onChange(e.currentTarget.value)} />;
  }
}

/** Read-only display of field values. */
export function FieldsView({ defs, values }: { defs: FieldDef[]; values: Record<string, unknown> }) {
  const users = useDirectory().data ?? [];
  const shown = defs.filter((f) => f.type !== "text");
  if (!shown.length) return null;
  return (
    <SimpleGrid cols={{ base: 2, md: 3 }} spacing="xs" verticalSpacing="xs">
      {shown.map((f) => {
        let v = values[f.key];
        if (f.type === "enum") v = f.options.find((o) => o.key === v)?.label ?? v;
        if (f.type === "multienum" && Array.isArray(v)) v = v.map((x) => f.options.find((o) => o.key === x)?.label ?? x);
        if (f.type === "user") v = users.find((u) => u.id === v)?.display_name ?? v;
        return (
          <div key={f.key}>
            <Text size="xs" c="dimmed">{f.label}</Text>
            <Text size="sm" data-testid={`value-${f.key}`}>{fmtValue(v)}</Text>
          </div>
        );
      })}
    </SimpleGrid>
  );
}
