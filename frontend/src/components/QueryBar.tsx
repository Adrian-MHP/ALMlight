import { useEffect, useMemo, useState } from "react";
import {
  ActionIcon, Alert, Button, Checkbox, CloseButton, Code, CopyButton, Divider, Group, Menu, NumberInput, Popover, ScrollArea,
  SegmentedControl, Stack, TagsInput, Text, TextInput, Tooltip,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconCheck, IconCode, IconCopy, IconFilterPlus, IconSearch, IconX } from "@tabler/icons-react";
import { api, ApiError } from "@/api/client";
import type { Condition, QueryState } from "@/api/types";
import { conditionLabel, defaultOp, type QField } from "@/lib/queryFields";

interface Props {
  projectKey: string;
  value: QueryState;
  onChange: (v: QueryState) => void;
  fields: QField[];
}

/** Polarion-like query bar: free text, field chips with value pickers, and an editable query text. */
export function QueryBar({ projectKey, value, onChange, fields }: Props) {
  const [text, setText] = useState(value.q);
  const [debounced] = useDebouncedValue(text, 300);
  const [open, setOpen] = useState<number | null>(null);
  const [showQl, setShowQl] = useState(false);
  useEffect(() => { setText(value.q); }, [value.q]);
  useEffect(() => { if (debounced !== value.q) onChange({ ...value, q: debounced }); }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps
  const byId = useMemo(() => new Map(fields.map((f) => [f.id, f])), [fields]);
  const set = (i: number, c: Condition | null) => {
    const next = [...value.conditions];
    if (c === null) next.splice(i, 1); else next[i] = c;
    onChange({ ...value, conditions: next });
  };
  function add(f: QField) {
    const c: Condition = { field: f.id, op: defaultOp(f.kind), values: f.kind === "bool" || f.kind === "link" ? [true] : [] };
    onChange({ ...value, conditions: [...value.conditions, c] });
    setOpen(value.conditions.length);
  }
  return (
    <Stack gap={6} data-testid="query-bar">
      <Group gap={6} wrap="wrap" align="center">
        <TextInput placeholder="Search key, title, text…" leftSection={<IconSearch size={16} />} value={text}
          onChange={(e) => setText(e.currentTarget.value)} w={260} data-testid="items-search"
          rightSection={text ? <CloseButton size="sm" onClick={() => setText("")} aria-label="Clear search" /> : null} />
        {value.conditions.map((c, i) => (
          <Popover key={i} opened={open === i} onChange={(o) => setOpen(o ? i : null)} position="bottom-start" shadow="md" width={320} trapFocus>
            <Popover.Target>
              <Button.Group>
                <Button size="xs" variant="light" color={c.not ? "orange" : undefined} onClick={() => setOpen(open === i ? null : i)}
                  data-testid={`qchip-${c.field}`} className="qchip">
                  {conditionLabel(c, byId.get(c.field))}
                </Button>
                <Button size="xs" variant="light" color={c.not ? "orange" : undefined} px={6} onClick={() => set(i, null)}
                  aria-label={`Remove filter ${byId.get(c.field)?.label ?? c.field}`} data-testid={`qchip-remove-${c.field}`}>
                  <IconX size={12} />
                </Button>
              </Button.Group>
            </Popover.Target>
            <Popover.Dropdown data-testid="qedit">
              <ConditionEditor c={c} field={byId.get(c.field)} onChange={(n) => set(i, n)} onDone={() => setOpen(null)} />
            </Popover.Dropdown>
          </Popover>
        ))}
        <AddFilter fields={fields} onAdd={add} />
        <Tooltip label="Query text (copy, paste, edit)">
          <ActionIcon variant={showQl ? "light" : "subtle"} color="gray" onClick={() => setShowQl((s) => !s)} data-testid="qtext-toggle" aria-label="Query text">
            <IconCode size={18} />
          </ActionIcon>
        </Tooltip>
        {(value.conditions.length > 0 || value.q) && (
          <Button size="xs" variant="subtle" color="gray" onClick={() => { setText(""); onChange({ q: "", conditions: [] }); }} data-testid="qclear">Clear</Button>
        )}
      </Group>
      {showQl && <QueryText projectKey={projectKey} value={value} onChange={onChange} />}
    </Stack>
  );
}

function AddFilter({ fields, onAdd }: { fields: QField[]; onAdd: (f: QField) => void }) {
  const [search, setSearch] = useState("");
  const shown = fields.filter((f) => f.label.toLowerCase().includes(search.toLowerCase()) || f.id.includes(search.toLowerCase()));
  const groups = Array.from(new Set(shown.map((f) => f.group)));
  return (
    <Menu position="bottom-start" width={290} onClose={() => setSearch("")} closeOnItemClick>
      <Menu.Target>
        <Button size="xs" variant="default" leftSection={<IconFilterPlus size={14} />} data-testid="qadd">Filter</Button>
      </Menu.Target>
      <Menu.Dropdown>
        <TextInput size="xs" placeholder="Find a field…" value={search} onChange={(e) => setSearch(e.currentTarget.value)} mb={4}
          data-testid="qadd-search" autoFocus onKeyDown={(e) => e.stopPropagation()} />
        <ScrollArea.Autosize mah={360}>
          {groups.map((g) => (
            <div key={g}>
              <Menu.Label>{g}</Menu.Label>
              {shown.filter((f) => f.group === g).map((f) => (
                <Menu.Item key={f.id} onClick={() => onAdd(f)} data-testid={`qfield-${f.id}`}>{f.label}</Menu.Item>
              ))}
            </div>
          ))}
          {shown.length === 0 && <Text size="xs" c="dimmed" p="xs">No field matches.</Text>}
        </ScrollArea.Autosize>
      </Menu.Dropdown>
    </Menu>
  );
}

const PRESETS: { label: string; values: [string | null, string | null] }[] = [
  { label: "Today", values: ["today", "today"] }, { label: "Last 7 days", values: ["-7d", "today"] },
  { label: "Last 30 days", values: ["-30d", "today"] }, { label: "Next 14 days", values: ["today", "+14d"] },
  { label: "Before today", values: [null, "-1d"] },
];

function ConditionEditor({ c, field, onChange, onDone }: { c: Condition; field?: QField; onChange: (c: Condition) => void; onDone: () => void }) {
  const kind = field?.kind ?? "text";
  const neg = (
    <SegmentedControl size="xs" fullWidth value={c.not ? "not" : "is"} onChange={(v) => onChange({ ...c, not: v === "not" })}
      data={[{ value: "is", label: kind === "text" ? "contains" : "is" }, { value: "not", label: kind === "text" ? "does not contain" : "is not" }]}
      data-testid="qedit-negate" />
  );
  const header = <Text size="sm" fw={600}>{field?.label ?? c.field}</Text>;
  if (kind === "bool") {
    return (
      <Stack gap="xs">{header}
        <SegmentedControl fullWidth value={String(c.values[0] === false || c.values[0] === "false" ? "false" : "true")}
          onChange={(v) => onChange({ ...c, op: "is", values: [v === "true"] })} data={[{ value: "true", label: "Yes" }, { value: "false", label: "No" }]} />
        <Button size="xs" onClick={onDone}>Done</Button>
      </Stack>
    );
  }
  if (kind === "link") {
    const mode = c.op === "in" ? "to" : (c.not ? c.values[0] === false : c.values[0] !== false) ? "any" : "none";
    return (
      <Stack gap="xs">{header}
        <SegmentedControl fullWidth size="xs" value={mode} data-testid="qedit-link"
          onChange={(v) => onChange(v === "to" ? { field: c.field, op: "in", values: [] }
            : { field: c.field, op: "exists", values: [true], not: v === "none" })}
          data={[{ value: "any", label: "Has links" }, { value: "none", label: "Has none" }, { value: "to", label: "To items" }]} />
        {mode === "to" && <TagsInput size="xs" placeholder="Item keys, e.g. TC-1" value={c.values.map(String)}
          onChange={(v) => onChange({ ...c, values: v.map((x) => x.toUpperCase()) })} />}
        <Button size="xs" onClick={onDone}>Done</Button>
      </Stack>
    );
  }
  if (kind === "number" || kind === "date") {
    const mode = c.op === "exists" ? ((c.not ? c.values[0] === false : c.values[0] !== false) ? "has" : "empty") : "range";
    const [lo, hi] = (c.op === "between" ? c.values : [null, null]) as (string | number | null)[];
    return (
      <Stack gap="xs">{header}
        <SegmentedControl fullWidth size="xs" value={mode}
          onChange={(v) => onChange(v === "range" ? { field: c.field, op: "between", values: [null, null], not: c.not }
            : { field: c.field, op: "exists", values: [true], not: v === "empty" })}
          data={[{ value: "range", label: kind === "date" ? "Period" : "Range" }, { value: "has", label: "Has a value" }, { value: "empty", label: "Empty" }]} />
        {mode === "range" && kind === "number" && (
          <Group grow>
            <NumberInput size="xs" label="From" value={lo ?? ""} onChange={(v) => onChange({ ...c, values: [v === "" ? null : v, hi ?? null] })} data-testid="qedit-min" />
            <NumberInput size="xs" label="To" value={hi ?? ""} onChange={(v) => onChange({ ...c, values: [lo ?? null, v === "" ? null : v] })} data-testid="qedit-max" />
          </Group>
        )}
        {mode === "range" && kind === "date" && (
          <>
            <Group grow>
              <TextInput size="xs" label="From" placeholder="2026-01-31, -7d" value={lo ?? ""} onChange={(e) => onChange({ ...c, values: [e.currentTarget.value || null, hi ?? null] })} data-testid="qedit-from" />
              <TextInput size="xs" label="To" placeholder="today, +14d" value={hi ?? ""} onChange={(e) => onChange({ ...c, values: [lo ?? null, e.currentTarget.value || null] })} data-testid="qedit-to" />
            </Group>
            <Group gap={4}>
              {PRESETS.map((p) => <Button key={p.label} size="compact-xs" variant="default" onClick={() => onChange({ ...c, values: p.values })}>{p.label}</Button>)}
            </Group>
          </>
        )}
        {mode === "range" && neg}
        <Button size="xs" onClick={onDone}>Done</Button>
      </Stack>
    );
  }
  if (kind === "text") {
    return (
      <Stack gap="xs">{header}{neg}
        <TagsInput size="xs" placeholder="Words (any of them), Enter after each" value={c.values.map(String)}
          onChange={(v) => onChange({ ...c, op: "contains", values: v })} data-testid="qedit-words" autoFocus />
        <Button size="xs" onClick={onDone}>Done</Button>
      </Stack>
    );
  }
  return <OptionPicker c={c} field={field} onChange={onChange} onDone={onDone} neg={neg} header={header} />;
}

function OptionPicker({ c, field, onChange, onDone, neg, header }: {
  c: Condition; field?: QField; onChange: (c: Condition) => void; onDone: () => void; neg: React.ReactNode; header: React.ReactNode;
}) {
  const [search, setSearch] = useState("");
  const [free, setFree] = useState("");
  const selected = new Set(c.values.map(String));
  const options = (field?.options ?? []).concat(c.values.map(String).filter((v) => !(field?.options ?? []).some((o) => o.value === v))
    .map((v) => ({ value: v, label: v })));
  const shown = options.filter((o) => o.label.toLowerCase().includes(search.toLowerCase()) || o.value.toLowerCase().includes(search.toLowerCase()));
  const toggle = (v: string) => onChange({ ...c, op: "in", values: selected.has(v) ? c.values.filter((x) => String(x) !== v) : [...c.values, v] });
  return (
    <Stack gap="xs">
      {header}
      {neg}
      {options.length > 6 && <TextInput size="xs" placeholder="Search…" leftSection={<IconSearch size={12} />} value={search}
        onChange={(e) => setSearch(e.currentTarget.value)} data-testid="qedit-search" autoFocus />}
      <ScrollArea.Autosize mah={240}>
        <Stack gap={4}>
          {shown.map((o) => (
            <Checkbox key={o.value} size="xs" label={o.label} checked={selected.has(o.value)} onChange={() => toggle(o.value)}
              data-testid={`qopt-${o.value}`} />
          ))}
          {shown.length === 0 && <Text size="xs" c="dimmed">No values.</Text>}
        </Stack>
      </ScrollArea.Autosize>
      {field?.free && (
        <Group gap={4} wrap="nowrap">
          <TextInput size="xs" style={{ flex: 1 }} placeholder="Add a value…" value={free} onChange={(e) => setFree(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && free.trim()) { toggle(field.id === "key" ? free.trim().toUpperCase() : free.trim()); setFree(""); } }}
            data-testid="qedit-free" />
        </Group>
      )}
      <Divider />
      <Group justify="space-between">
        <Group gap={4}>
          <Button size="compact-xs" variant="subtle" onClick={() => onChange({ ...c, op: "in", values: shown.map((o) => o.value) })}>All</Button>
          <Button size="compact-xs" variant="subtle" onClick={() => onChange({ ...c, op: "in", values: [] })}>None</Button>
        </Group>
        <Button size="xs" onClick={onDone} data-testid="qedit-done">Done</Button>
      </Group>
    </Stack>
  );
}

function QueryText({ projectKey, value, onChange }: { projectKey: string; value: QueryState; onChange: (v: QueryState) => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api.post<{ text: string }>(`/projects/${projectKey}/query/format`, { q: value.q || null, conditions: value.conditions })
      .then((r) => { if (!cancelled) { setText(r.text); setDirty(false); setError(null); } })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [projectKey, value]);
  async function apply() {
    try {
      const r = await api.post<{ q: string | null; conditions: Condition[] }>(`/projects/${projectKey}/query/parse`, { text });
      setError(null);
      onChange({ q: r.q ?? "", conditions: r.conditions });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }
  return (
    <Stack gap={4}>
      <Group gap={6} wrap="nowrap" align="flex-start">
        <TextInput style={{ flex: 1 }} size="xs" styles={{ input: { fontFamily: "var(--mantine-font-family-monospace)" } }} value={text} placeholder="type:system_requirement state:(draft OR in_review) NOT link.verifies.in:*"
          onChange={(e) => { setText(e.currentTarget.value); setDirty(true); }} onKeyDown={(e) => { if (e.key === "Enter") apply(); }}
          data-testid="qtext" error={!!error} />
        <Button size="xs" onClick={apply} disabled={!dirty} data-testid="qtext-apply">Apply</Button>
        <CopyButton value={text}>
          {({ copied, copy }) => (
            <Tooltip label={copied ? "Copied" : "Copy query"}>
              <ActionIcon variant="subtle" color={copied ? "teal" : "gray"} onClick={copy} aria-label="Copy query">{copied ? <IconCheck size={16} /> : <IconCopy size={16} />}</ActionIcon>
            </Tooltip>
          )}
        </CopyButton>
      </Group>
      {error ? <Alert color="red" py={4} data-testid="qtext-error">{error}</Alert> : (
        <Text size="xs" c="dimmed">Clauses are combined with AND; <Code>OR</Code> inside parentheses, <Code>NOT</Code> negates,
          <Code>field:*</Code> = has a value, <Code>[a TO b]</Code> ranges, dates like <Code>-7d</Code>, users <Code>me</Code>.</Text>
      )}
    </Stack>
  );
}
