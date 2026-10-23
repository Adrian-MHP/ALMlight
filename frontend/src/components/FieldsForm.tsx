import { Badge, Checkbox, MultiSelect, NumberInput, Select, SimpleGrid, TagsInput, Text, Textarea, TextInput } from "@mantine/core";
import type { FieldDef, TestStep } from "@/api/types";
import { StepsEditor } from "./TestSteps";
import { useDirectory } from "@/api/hooks";
import { fmtValue } from "@/lib/format";
import { withComputed } from "@/lib/formula";

/** Form inputs generated from the configured field definitions of an item type. */
export function FieldsForm({ defs, values, onChange }: {
  defs: FieldDef[];
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  const users = useDirectory().data ?? [];
  if (!defs.length) return null;
  const shown = withComputed(defs, values);
  const wide = defs.filter((f) => f.type === "text");
  const steps = defs.filter((f) => f.type === "steps");
  const narrow = defs.filter((f) => f.type !== "text" && f.type !== "steps");
  return (
    <>
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
        {narrow.map((f) => <FieldInput key={f.key} def={f} value={shown[f.key]} onChange={(v) => onChange(f.key, v)} users={users} />)}
      </SimpleGrid>
      {wide.map((f) => <FieldInput key={f.key} def={f} value={shown[f.key]} onChange={(v) => onChange(f.key, v)} users={users} />)}
      {steps.map((f) => <StepsEditor key={f.key} label={f.label} value={values[f.key] as TestStep[]} onChange={(v) => onChange(f.key, v)} />)}
    </>
  );
}

function FieldInput({ def, value, onChange, users }: {
  def: FieldDef; value: unknown; onChange: (v: unknown) => void; users: { id: string; display_name: string }[];
}) {
  const common = { label: def.label, description: def.help ?? undefined, required: def.required, "data-testid": `field-${def.key}` };
  if (def.formula || def.classify) {
    const shown = def.type === "enum" ? def.options.find((o) => o.key === value)?.label ?? (value as string) : value;
    return (
      <TextInput {...common} readOnly value={shown === undefined || shown === null ? "–" : String(shown)}
        description={def.formula ? `Calculated: ${def.formula}` : `Calculated from ${def.classify?.field}`}
        rightSection={<Badge size="xs" variant="light" color="gray">calc</Badge>} rightSectionWidth={52} />
    );
  }
  switch (def.type) {
    case "text":
      return <Textarea {...common} autosize minRows={2} maxRows={10} value={(value as string) ?? ""} onChange={(e) => onChange(e.currentTarget.value)} />;
    case "integer":
    case "number":
      return <NumberInput {...common} value={(value as number) ?? ""} allowDecimal={def.type === "number"}
        min={def.min ?? undefined} max={def.max ?? undefined}
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
  const shown = defs.filter((f) => f.type !== "text" && f.type !== "steps");
  if (!shown.length) return null;
  return (
    <SimpleGrid cols={{ base: 2, md: 3 }} spacing="xs" verticalSpacing="xs">
      {shown.map((f) => {
        let v = values[f.key];
        if (f.type === "enum") v = f.options.find((o) => o.key === v)?.label ?? v;
        if (f.type === "multienum" && Array.isArray(v)) v = v.map((x) => f.options.find((o) => o.key === x)?.label ?? x);
        if (f.type === "user") v = users.find((u) => u.id === v)?.display_name ?? v;
        const option = f.type === "enum" ? f.options.find((o) => o.key === values[f.key]) : undefined;
        return (
          <div key={f.key}>
            <Text size="xs" c="dimmed">{f.label}</Text>
            {option?.color ? <Badge color={option.color} variant="light" data-testid={`value-${f.key}`}>{option.label}</Badge>
              : <Text size="sm" data-testid={`value-${f.key}`} fw={f.formula ? 600 : undefined}>{fmtValue(v)}</Text>}
          </div>
        );
      })}
    </SimpleGrid>
  );
}
