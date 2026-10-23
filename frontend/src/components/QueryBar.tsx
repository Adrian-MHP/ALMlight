import { useEffect, useMemo, useState } from "react";
import {
  ActionIcon, Alert, Button, Checkbox, CloseButton, Code, CopyButton, Divider, Group, Menu, NumberInput, Popover, ScrollArea,
  SegmentedControl, Stack, TagsInput, Text, TextInput, Tooltip,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconArrowLeft, IconCheck, IconCode, IconCopy, IconFilterPlus, IconSearch, IconX } from "@tabler/icons-react";
import { api, ApiError } from "@/api/client";
import type { CondGroup, Condition, QNode, QueryState } from "@/api/types";
import { children, collapse, defaultOp, groupKind, isGroup, makeGroup, nodeLabel, type QField } from "@/lib/queryFields";
import { tx } from "@/lib/i18n";

interface Props {
  projectKey: string;
  value: QueryState;
  onChange: (v: QueryState) => void;
  fields: QField[];
}

/** Polarion-like query bar: free text, field chips with value pickers, OR/AND groups, and an editable query text. */
export function QueryBar({ projectKey, value, onChange, fields }: Props) {
  const [text, setText] = useState(value.q);
  const [debounced] = useDebouncedValue(text, 300);
  const [open, setOpen] = useState<number | null>(null);
  const [showQl, setShowQl] = useState(false);
  useEffect(() => { setText(value.q); }, [value.q]);
  useEffect(() => { if (debounced !== value.q) onChange({ ...value, q: debounced }); }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps
  const byId = useMemo(() => new Map(fields.map((f) => [f.id, f])), [fields]);
  const set = (i: number, n: QNode | null) => {
    const next = [...value.conditions];
    if (n === null) next.splice(i, 1); else next[i] = n;
    onChange({ ...value, conditions: next });
  };
  function split(i: number) {
    const g = value.conditions[i];
    if (!isGroup(g)) return;
    const next = [...value.conditions];
    next.splice(i, 1, ...children(g));
    onChange({ ...value, conditions: next });
    setOpen(null);
  }
  function add(f: QField) {
    onChange({ ...value, conditions: [...value.conditions, newCondition(f)] });
    setOpen(value.conditions.length);
  }
  return (
    <Stack gap={6} data-testid="query-bar">
      <Group gap={6} wrap="wrap" align="center">
        <TextInput placeholder={tx("Search key, title, text…")} leftSection={<IconSearch size={16} />} value={text}
          onChange={(e) => setText(e.currentTarget.value)} w={260} data-testid="items-search"
          rightSection={text ? <CloseButton size="sm" onClick={() => setText("")} aria-label={tx("Clear search")} /> : null} />
        {value.conditions.map((n, i) => (
          <NodeChip key={i} index={i} node={n} byId={byId} fields={fields} opened={open === i}
            onOpen={(o) => setOpen(o ? i : null)} onChange={(x) => set(i, x)} onSplit={() => split(i)} />
        ))}
        <AddFilter fields={fields} onAdd={add} />
        <Tooltip label={tx("Query text (copy, paste, edit)")}>
          <ActionIcon variant={showQl ? "light" : "subtle"} color="gray" onClick={() => setShowQl((s) => !s)} data-testid="qtext-toggle" aria-label={tx("Query text")}>
            <IconCode size={18} />
          </ActionIcon>
        </Tooltip>
        {(value.conditions.length > 0 || value.q) && (
          <Button size="xs" variant="subtle" color="gray" onClick={() => { setText(""); onChange({ q: "", conditions: [] }); }} data-testid="qclear">{tx("Clear")}</Button>
        )}
      </Group>
      {showQl && <QueryText projectKey={projectKey} value={value} onChange={onChange} />}
    </Stack>
  );
}

function newCondition(f: QField): Condition {
  return { field: f.id, op: defaultOp(f.kind), values: f.kind === "bool" || f.kind === "link" ? [true] : [] };
}

function NodeChip({ index, node, byId, fields, opened, onOpen, onChange, onSplit }: {
  index: number; node: QNode; byId: Map<string, QField>; fields: QField[]; opened: boolean;
  onOpen: (o: boolean) => void; onChange: (n: QNode | null) => void; onSplit: () => void;
}) {
  const [focus, setFocus] = useState<number | null>(null);
  const show = (o: boolean) => { onOpen(o); if (!o) setFocus(null); };
  const group = isGroup(node);
  const label = nodeLabel(node, byId);
  const color = node.not ? "orange" : group ? "grape" : undefined;
  const name = group ? "group" : byId.get(node.field)?.label ?? node.field;
  return (
    <Popover opened={opened} onChange={show} position="bottom-start" shadow="md"
      width={group ? 360 : 320} trapFocus>
      <Popover.Target>
        <Button.Group>
          <Button size="xs" variant="light" color={color} onClick={() => show(!opened)} title={label} className="qchip"
            data-testid={group ? `qgroup-${index}` : `qchip-${node.field}`}>
            {label}
          </Button>
          <Button size="xs" variant="light" color={color} px={6} onClick={() => onChange(null)} aria-label={tx("Remove filter {name}", { name: name })}
            data-testid={group ? `qgroup-remove-${index}` : `qchip-remove-${node.field}`}>
            <IconX size={12} />
          </Button>
        </Button.Group>
      </Popover.Target>
      <Popover.Dropdown data-testid="qedit">
        {group ? (
          <GroupEditor g={node} byId={byId} fields={fields} initialEdit={focus} onChange={onChange} onSplit={onSplit}
            onDone={() => show(false)} />
        ) : (
          <Stack gap="xs">
            <ConditionEditor c={node} field={byId.get(node.field)} onChange={onChange} onDone={() => show(false)} />
            <Divider label={tx("or match another condition")} labelPosition="center" />
            <AddFilter fields={fields} inline label={tx("OR …")} testid="qor"
              onAdd={(f) => { setFocus(1); onChange(makeGroup("or", [node, newCondition(f)])); }} />
          </Stack>
        )}
      </Popover.Dropdown>
    </Popover>
  );
}

/** Edits an OR/AND group: its members (conditions or nested groups), the combination and the negation. */
function GroupEditor({ g, byId, fields, initialEdit, onChange, onDone, onSplit }: {
  g: CondGroup; byId: Map<string, QField>; fields: QField[]; initialEdit?: number | null;
  onChange: (n: QNode | null) => void; onDone: () => void; onSplit?: () => void;
}) {
  const [editing, setEditing] = useState<number | null>(initialEdit ?? null);
  const kids = children(g);
  const kind = groupKind(g);
  const setKid = (i: number, n: QNode | null) => {
    const next = [...kids];
    if (n === null) next.splice(i, 1); else next[i] = n;
    if (next.length === 0) { onChange(null); return; }
    setEditing(null);
    onChange(collapse(makeGroup(kind, next, g.not)));
  };
  const current = editing !== null ? kids[editing] : undefined;
  if (current && editing !== null) {
    const back = (
      <Button size="compact-xs" variant="subtle" leftSection={<IconArrowLeft size={12} />} onClick={() => setEditing(null)}
        data-testid="qgroup-back" style={{ alignSelf: "flex-start" }}>
        {tx("Group")}
      </Button>
    );
    const change = (n: QNode | null) => {
      const next = [...kids];
      if (n === null) { setKid(editing, null); return; }
      next[editing] = n;
      onChange(makeGroup(kind, next, g.not));
    };
    return (
      <Stack gap="xs">
        {back}
        {isGroup(current)
          ? <GroupEditor g={current} byId={byId} fields={fields} onChange={change} onDone={() => setEditing(null)} />
          : <ConditionEditor c={current} field={byId.get(current.field)} onChange={change} onDone={() => setEditing(null)} />}
      </Stack>
    );
  }
  const joiner = kind === "or" ? "OR" : "AND";
  return (
    <Stack gap="xs" data-testid="qgroup-editor">
      <Text size="sm" fw={600}>{tx("Filter group")}</Text>
      <SegmentedControl fullWidth size="xs" value={kind} data-testid="qgroup-kind"
        onChange={(v) => onChange(makeGroup(v as "or" | "and", kids, g.not))}
        data={[{ value: "or", label: tx("Any matches (OR)") }, { value: "and", label: tx("All match (AND)") }]} />
      <SegmentedControl fullWidth size="xs" value={g.not ? "not" : "is"} data-testid="qgroup-negate"
        onChange={(v) => onChange(makeGroup(kind, kids, v === "not"))}
        data={[{ value: "is", label: tx("Include") }, { value: "not", label: tx("Exclude (NOT)") }]} />
      <Stack gap={2}>
        {kids.map((k, i) => (
          <div key={i}>
            {i > 0 && <Text size="xs" c="dimmed" ta="center" fw={600}>{joiner}</Text>}
            <Group gap={4} wrap="nowrap">
              <Button size="xs" variant="light" color={k.not ? "orange" : isGroup(k) ? "grape" : undefined} style={{ flex: 1, minWidth: 0 }}
                justify="flex-start" className="qchip" onClick={() => setEditing(i)} data-testid={`qmember-${i}`}>
                {nodeLabel(k, byId, true)}
              </Button>
              <ActionIcon variant="subtle" color="gray" onClick={() => setKid(i, null)} aria-label={tx("Remove from group")}
                data-testid={`qmember-remove-${i}`}>
                <IconX size={14} />
              </ActionIcon>
            </Group>
          </div>
        ))}
      </Stack>
      <Divider />
      <Group justify="space-between" gap={4}>
        <AddFilter fields={fields} inline label={`${joiner} …`} testid="qgroup-add"
          onAdd={(f) => { const i = kids.length; onChange(makeGroup(kind, [...kids, newCondition(f)], g.not)); setEditing(i); }} />
        <Group gap={4}>
          {onSplit && (
            <Tooltip label={tx("Each member becomes its own filter; all of them must then match")} withinPortal={false}>
              <Button size="compact-xs" variant="subtle" color="gray" onClick={onSplit} data-testid="qgroup-split">{tx("Split")}</Button>
            </Tooltip>
          )}
          <Button size="xs" onClick={onDone} data-testid="qgroup-done">{tx("Done")}</Button>
        </Group>
      </Group>
    </Stack>
  );
}

function AddFilter({ fields, onAdd, label = tx("Filter"), testid = "qadd", inline = false }: {
  fields: QField[]; onAdd: (f: QField) => void; label?: string; testid?: string; inline?: boolean;
}) {
  const [search, setSearch] = useState("");
  const shown = fields.filter((f) => f.label.toLowerCase().includes(search.toLowerCase()) || f.id.includes(search.toLowerCase()));
  const groups = Array.from(new Set(shown.map((f) => f.group)));
  return (
    <Menu position="bottom-start" width={290} onClose={() => setSearch("")} closeOnItemClick withinPortal={!inline}>
      <Menu.Target>
        <Button size="xs" variant={inline ? "light" : "default"} leftSection={<IconFilterPlus size={14} />} data-testid={testid}>{label}</Button>
      </Menu.Target>
      <Menu.Dropdown>
        <TextInput size="xs" placeholder={tx("Find a field…")} value={search} onChange={(e) => setSearch(e.currentTarget.value)} mb={4}
          data-testid={`${testid}-search`} autoFocus onKeyDown={(e) => e.stopPropagation()} />
        <ScrollArea.Autosize mah={inline ? 260 : 360}>
          {groups.map((g) => (
            <div key={g}>
              <Menu.Label>{g}</Menu.Label>
              {shown.filter((f) => f.group === g).map((f) => (
                <Menu.Item key={f.id} onClick={() => onAdd(f)} data-testid={`qfield-${f.id}`}>{f.label}</Menu.Item>
              ))}
            </div>
          ))}
          {shown.length === 0 && <Text size="xs" c="dimmed" p="xs">{tx("No field matches.")}</Text>}
        </ScrollArea.Autosize>
      </Menu.Dropdown>
    </Menu>
  );
}

const PRESETS: { label: string; values: [string | null, string | null] }[] = [
  { label: tx("Today"), values: ["today", "today"] }, { label: tx("Last 7 days"), values: ["-7d", "today"] },
  { label: tx("Last 30 days"), values: ["-30d", "today"] }, { label: tx("Next 14 days"), values: ["today", "+14d"] },
  { label: tx("Before today"), values: [null, "-1d"] },
];

function ConditionEditor({ c, field, onChange, onDone }: { c: Condition; field?: QField; onChange: (c: Condition) => void; onDone: () => void }) {
  const kind = field?.kind ?? "text";
  const neg = (
    <SegmentedControl size="xs" fullWidth value={c.not ? "not" : "is"} onChange={(v) => onChange({ ...c, not: v === "not" })}
      data={[{ value: "is", label: kind === "text" ? tx("contains") : tx("is") }, { value: "not", label: kind === "text" ? tx("does not contain") : tx("is not") }]}
      data-testid="qedit-negate" />
  );
  const header = <Text size="sm" fw={600}>{field?.label ?? c.field}</Text>;
  if (kind === "bool") {
    return (
      <Stack gap="xs">{header}
        <SegmentedControl fullWidth value={String(c.values[0] === false || c.values[0] === "false" ? "false" : "true")}
          onChange={(v) => onChange({ ...c, op: "is", values: [v === "true"] })} data={[{ value: "true", label: tx("Yes") }, { value: "false", label: tx("No") }]} />
        <Button size="xs" onClick={onDone}>{tx("Done")}</Button>
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
          data={[{ value: "any", label: tx("Has links") }, { value: "none", label: tx("Has none") }, { value: "to", label: tx("To items") }]} />
        {mode === "to" && <TagsInput size="xs" placeholder={tx("Item keys, e.g. TC-1")} value={c.values.map(String)}
          onChange={(v) => onChange({ ...c, values: v.map((x) => x.toUpperCase()) })} />}
        <Button size="xs" onClick={onDone}>{tx("Done")}</Button>
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
          data={[{ value: "range", label: kind === "date" ? tx("Period") : tx("Range") }, { value: "has", label: tx("Has a value") }, { value: "empty", label: tx("Empty") }]} />
        {mode === "range" && kind === "number" && (
          <Group grow>
            <NumberInput size="xs" label={tx("From")} value={lo ?? ""} onChange={(v) => onChange({ ...c, values: [v === "" ? null : v, hi ?? null] })} data-testid="qedit-min" />
            <NumberInput size="xs" label={tx("To")} value={hi ?? ""} onChange={(v) => onChange({ ...c, values: [lo ?? null, v === "" ? null : v] })} data-testid="qedit-max" />
          </Group>
        )}
        {mode === "range" && kind === "date" && (
          <>
            <Group grow>
              <TextInput size="xs" label={tx("From")} placeholder="2026-01-31, -7d" value={lo ?? ""} onChange={(e) => onChange({ ...c, values: [e.currentTarget.value || null, hi ?? null] })} data-testid="qedit-from" />
              <TextInput size="xs" label={tx("To")} placeholder={tx("today, +14d")} value={hi ?? ""} onChange={(e) => onChange({ ...c, values: [lo ?? null, e.currentTarget.value || null] })} data-testid="qedit-to" />
            </Group>
            <Group gap={4}>
              {PRESETS.map((p) => <Button key={p.label} size="compact-xs" variant="default" onClick={() => onChange({ ...c, values: p.values })}>{p.label}</Button>)}
            </Group>
          </>
        )}
        {mode === "range" && neg}
        <Button size="xs" onClick={onDone}>{tx("Done")}</Button>
      </Stack>
    );
  }
  if (kind === "text") {
    return (
      <Stack gap="xs">{header}{neg}
        <TagsInput size="xs" placeholder={tx("Words (any of them), Enter after each")} value={c.values.map(String)}
          onChange={(v) => onChange({ ...c, op: "contains", values: v })} data-testid="qedit-words" autoFocus />
        <Button size="xs" onClick={onDone}>{tx("Done")}</Button>
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
      {options.length > 6 && <TextInput size="xs" placeholder={tx("Search…")} leftSection={<IconSearch size={12} />} value={search}
        onChange={(e) => setSearch(e.currentTarget.value)} data-testid="qedit-search" autoFocus />}
      <ScrollArea.Autosize mah={240}>
        <Stack gap={4}>
          {shown.map((o) => (
            <Checkbox key={o.value} size="xs" label={o.label} checked={selected.has(o.value)} onChange={() => toggle(o.value)}
              data-testid={`qopt-${o.value}`} />
          ))}
          {shown.length === 0 && <Text size="xs" c="dimmed">{tx("No values.")}</Text>}
        </Stack>
      </ScrollArea.Autosize>
      {field?.free && (
        <Group gap={4} wrap="nowrap">
          <TextInput size="xs" style={{ flex: 1 }} placeholder={tx("Add a value…")} value={free} onChange={(e) => setFree(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && free.trim()) { toggle(field.id === "key" ? free.trim().toUpperCase() : free.trim()); setFree(""); } }}
            data-testid="qedit-free" />
        </Group>
      )}
      <Divider />
      <Group justify="space-between">
        <Group gap={4}>
          <Button size="compact-xs" variant="subtle" onClick={() => onChange({ ...c, op: "in", values: shown.map((o) => o.value) })}>{tx("All")}</Button>
          <Button size="compact-xs" variant="subtle" onClick={() => onChange({ ...c, op: "in", values: [] })}>{tx("None")}</Button>
        </Group>
        <Button size="xs" onClick={onDone} data-testid="qedit-done">{tx("Done")}</Button>
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
      const r = await api.post<{ q: string | null; conditions: QNode[] }>(`/projects/${projectKey}/query/parse`, { text });
      setError(null);
      onChange({ q: r.q ?? "", conditions: r.conditions });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }
  return (
    <Stack gap={4}>
      <Group gap={6} wrap="nowrap" align="flex-start">
        <TextInput style={{ flex: 1 }} size="xs" styles={{ input: { fontFamily: "var(--mantine-font-family-monospace)" } }} value={text} placeholder={tx("type:system_requirement state:(draft OR in_review) NOT link.verifies.in:*")}
          onChange={(e) => { setText(e.currentTarget.value); setDirty(true); }} onKeyDown={(e) => { if (e.key === "Enter") apply(); }}
          data-testid="qtext" error={!!error} />
        <Button size="xs" onClick={apply} disabled={!dirty} data-testid="qtext-apply">{tx("Apply")}</Button>
        <CopyButton value={text}>
          {({ copied, copy }) => (
            <Tooltip label={copied ? tx("Copied") : tx("Copy query")}>
              <ActionIcon variant="subtle" color={copied ? "teal" : "gray"} onClick={copy} aria-label={tx("Copy query")}>{copied ? <IconCheck size={16} /> : <IconCopy size={16} />}</ActionIcon>
            </Tooltip>
          )}
        </CopyButton>
      </Group>
      {error ? <Alert color="red" py={4} data-testid="qtext-error">{error}</Alert> : (
        <Text size="xs" c="dimmed">{tx("Clauses are combined with AND;")} <Code>OR</Code> {tx("between clauses or values,")} <Code>( )</Code> {tx("groups,")} <Code>NOT</Code> {tx("negates,")}
          <Code>field:*</Code> {tx("= has a value,")} <Code>[a TO b]</Code> {tx("ranges, dates like")} <Code>-7d</Code>{tx(", users")} <Code>me</Code>.</Text>
      )}
    </Stack>
  );
}
