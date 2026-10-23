import { useEffect, useMemo, useState } from "react";
import {
  ActionIcon, Badge, Button, Card, Checkbox, Grid, Group, Menu, Modal, Pagination, Popover, ScrollArea, Stack, Table, Text,
  TextInput, Tooltip, UnstyledButton,
} from "@mantine/core";
import {
  IconArrowDown, IconArrowUp, IconBookmark, IconColumns, IconDeviceFloppy, IconDots, IconDownload, IconEdit, IconEye,
  IconEyeOff, IconLayoutSidebarRight, IconLink, IconPlus, IconRoute, IconTarget, IconTrash,
} from "@tabler/icons-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, downloadUrl, qs } from "@/api/client";
import { useDirectory, useItems, useProjectMutation, useSavedQueries } from "@/api/hooks";
import type { FieldDef, Item, QNode, QueryState, SavedQuery } from "@/api/types";
import { BulkModal, type BulkAction } from "@/components/BulkEdit";
import { ItemPreview } from "@/components/ItemPreview";
import { ItemLink, StateBadge, TypeBadge } from "@/components/badges";
import { PageHeader } from "@/components/PageHeader";
import { QueryBar } from "@/components/QueryBar";
import { fmtRelative } from "@/lib/format";
import { legacyToConditions, queryFields, topLeaves } from "@/lib/queryFields";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";
import { tx } from "@/lib/i18n";

const PAGE = 50;

interface Col { id: string; label: string; sort?: string; w?: number; render: (i: Item) => React.ReactNode }

function readStore<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v ? (JSON.parse(v) as T) : fallback; } catch { return fallback; }
}
function writeStore(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

function parseConditions(raw: string | null): QNode[] {
  if (!raw) return [];
  try { const v = JSON.parse(raw); return Array.isArray(v) ? v : []; } catch { return []; }
}

/** The item list: Polarion-like query builder, configurable columns, sorting, bulk edit and a preview pane. */
export function ItemsPage() {
  const { key, model, can } = useProjectCtx();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const users = useDirectory().data ?? [];
  const query: QueryState = useMemo(() => {
    const conditions = parseConditions(params.get("cond"));
    const legacyType = params.get("type");
    if (legacyType && !topLeaves(conditions).some((c) => c.field === "type")) conditions.unshift({ field: "type", op: "in", values: [legacyType] });
    return { q: params.get("q") ?? "", conditions };
  }, [params]);
  const sort = params.get("sort") ?? "key";
  const [page, setPage] = useState(1);
  const typeCond = topLeaves(query.conditions).find((c) => c.field === "type" && c.op === "in" && !c.not);
  const types = useMemo(() => (typeCond?.values as string[] | undefined) ?? [], [typeCond]);
  const singleType = types.length === 1 ? model.type(types[0]) : undefined;
  const releases = useItems(key, { type: model.releaseType ? [model.releaseType.key] : [], limit: 200 }, !!model.releaseType).data?.items ?? [];
  const releaseOptions = useMemo(() => releases.map((r) => ({ value: r.key, label: `${r.key} — ${r.title}` })), [releases]);
  const fields = useMemo(() => queryFields(model, { users, types, releases: releaseOptions }), [model, users, releaseOptions, types]);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allMatching, setAllMatching] = useState(false);
  function setQuery(next: QueryState, nextSort = sort) {
    const p = new URLSearchParams(params);
    p.delete("type");
    if (next.q) p.set("q", next.q); else p.delete("q");
    if (next.conditions.length) p.set("cond", JSON.stringify(next.conditions)); else p.delete("cond");
    if (nextSort && nextSort !== "key") p.set("sort", nextSort); else p.delete("sort");
    setParams(p, { replace: true });
    setPage(1);
    setSelected(new Set());
    setAllMatching(false);
  }
  const { data, isFetching } = useItems(key, { q: query.q || undefined, conditions: query.conditions, sort, limit: PAGE, offset: (page - 1) * PAGE });

  // --- columns -----------------------------------------------------------------------------------------
  const allFieldDefs = useMemo(() => {
    const map = new Map<string, FieldDef>();
    for (const t of types.length ? types.map((k) => model.type(k)!).filter(Boolean) : model.config.item_types) {
      for (const f of t.fields) if (f.type !== "steps" && f.type !== "text" && !map.has(f.key)) map.set(f.key, f);
    }
    return [...map.values()];
  }, [model, types]);
  const fmtField = (f: FieldDef, v: unknown): React.ReactNode => {
    if (v === undefined || v === null || v === "") return "";
    if (f.type === "enum") {
      const o = f.options?.find((x) => x.key === v);
      return o?.color ? <Badge size="xs" variant="light" color={o.color}>{o.label}</Badge> : o?.label ?? String(v);
    }
    if (f.type === "boolean") return v ? tx("Yes") : tx("No");
    if (f.type === "user") return users.find((u) => u.id === v)?.display_name ?? String(v);
    if (Array.isArray(v)) return v.map((x) => f.options?.find((o) => o.key === x)?.label ?? x).join(", ");
    return String(v);
  };
  const columns: Record<string, Col> = {
    key: { id: "key", label: tx("Key"), sort: "key", w: 110, render: (i) => <ItemLink item={i} /> },
    title: { id: "title", label: tx("Title"), sort: "title", render: (i) => <Text size="sm" lineClamp={1} style={{ minWidth: 200 }}>{i.title}</Text> },
    type: { id: "type", label: tx("Type"), sort: "type", w: 190, render: (i) => <TypeBadge typeKey={i.type_key} /> },
    state: { id: "state", label: tx("Status"), sort: "state", w: 130, render: (i) => <StateBadge item={i} /> },
    version: { id: "version", label: tx("Version"), sort: "version", w: 80, render: (i) => <Text size="sm" className="mono">{i.version}</Text> },
    owner: { id: "owner", label: tx("Owner"), sort: "owner", w: 150, render: (i) => <Text size="sm" truncate>{i.owner?.display_name ?? "–"}</Text> },
    updated: { id: "updated", label: tx("Updated"), sort: "updated", w: 110, render: (i) => <Text size="xs" c="dimmed">{fmtRelative(i.updated_at)}</Text> },
    created: { id: "created", label: tx("Created"), sort: "created", w: 110, render: (i) => <Text size="xs" c="dimmed">{fmtRelative(i.created_at ?? null)}</Text> },
    author: { id: "author", label: tx("Created by"), w: 140, render: (i) => <Text size="sm" truncate>{i.author?.display_name ?? "–"}</Text> },
    applicability: { id: "applicability", label: tx("Applicability"), render: (i) => <Text size="xs" className="mono">{i.applicability ?? ""}</Text> },
  };
  for (const f of allFieldDefs) {
    columns[`field.${f.key}`] = { id: `field.${f.key}`, label: f.label, sort: `field.${f.key}`, render: (i) => <Text size="sm" component="div">{fmtField(f, i.fields[f.key])}</Text> };
  }
  const defaultCols = singleType
    ? ["key", "title", ...singleType.fields.filter((f) => ["enum", "string", "boolean", "integer", "number"].includes(f.type) && !f.formula).slice(0, 3).map((f) => `field.${f.key}`), "state", "version", "owner", "updated"]
    : ["key", "title", "type", "state", "version", "owner", "updated"];
  const colStore = `ariadne.columns.${key}.${singleType?.key ?? "all"}`;
  const [colIds, setColIds] = useState<string[]>(() => readStore(colStore, defaultCols));
  useEffect(() => { setColIds(readStore(colStore, defaultCols)); }, [colStore]); // eslint-disable-line react-hooks/exhaustive-deps
  const visible = colIds.map((c) => columns[c]).filter(Boolean);
  const setCols = (ids: string[]) => { setColIds(ids); writeStore(colStore, ids); };

  // --- selection & bulk ---------------------------------------------------------------------------------
  const [bulk, setBulk] = useState<BulkAction | null>(null);
  const pageKeys = data?.items.map((i) => i.key) ?? [];
  const allOnPage = pageKeys.length > 0 && pageKeys.every((k) => selected.has(k));
  const someOnPage = pageKeys.some((k) => selected.has(k));
  const selectionCount = allMatching ? data?.total ?? 0 : selected.size;
  const selectionTypes = allMatching ? types : Array.from(new Set((data?.items ?? []).filter((i) => selected.has(i.key)).map((i) => i.type_key)));
  const toggle = (k: string) => { const s = new Set(selected); if (s.has(k)) s.delete(k); else s.add(k); setSelected(s); setAllMatching(false); };

  // --- preview -------------------------------------------------------------------------------------------
  const [showPreview, setShowPreview] = useState<boolean>(() => readStore("ariadne.items.preview", true));
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const openRow = (i: Item) => { if (showPreview) setPreviewKey(i.key); else navigate(`/p/${key}/items/${i.key}`); };

  // --- views & export ------------------------------------------------------------------------------------
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const views = useSavedQueries(key).data ?? [];
  const delView = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/queries/${id}`), { success: tx("View deleted") });
  function applyView(v: SavedQuery) {
    const q = v.query as Record<string, unknown>;
    const cols = q.columns as string[] | undefined;
    setQuery({ q: (q.q as string) ?? "", conditions: legacyToConditions(q) }, (q.sort as string) ?? "key");
    if (cols?.length) setCols(cols);
  }
  const exportQs = qs({ q: query.q || undefined, cond: query.conditions.length ? JSON.stringify(query.conditions) : undefined, sort });
  const sortBy = (col: Col) => {
    if (!col.sort) return;
    setQuery(query, sort === col.sort ? `-${col.sort}` : col.sort);
  };

  return (
    <>
      <PageHeader title={singleType ? singleType.label : tx("All items")} subtitle={data ? tx("{total} item(s)", { total: data.total }) : undefined}
        actions={
          <>
            <Menu position="bottom-end" width={320}>
              <Menu.Target><Button variant="default" leftSection={<IconBookmark size={16} />} data-testid="views-menu">{tx("Views{v}", { v: views.length ? ` (${views.length})` : "" })}</Button></Menu.Target>
              <Menu.Dropdown>
                <Menu.Item leftSection={<IconDeviceFloppy size={14} />} onClick={() => setSaving(true)} data-testid="save-view">{tx("Save current query and columns as view…")}</Menu.Item>
                {views.length > 0 && <Menu.Divider />}
                {views.map((v) => (
                  <Menu.Item key={v.id} onClick={() => applyView(v)} data-testid={`view-${v.name}`}
                    rightSection={<Group gap={4} wrap="nowrap">
                      {v.count != null && <Badge size="xs" variant="light">{v.count}</Badge>}
                      {v.shared && <Badge size="xs" variant="outline" color="gray">{tx("shared")}</Badge>}
                      {v.can_edit && <IconTrash size={12} color="var(--mantine-color-red-6)" role="button" aria-label={tx("Delete view {name}", { name: v.name })}
                        data-testid={`view-delete-${v.name}`} onClick={(e) => { e.stopPropagation(); delView.mutate(v.id); }} />}
                    </Group>}>
                    {v.name}
                  </Menu.Item>
                ))}
              </Menu.Dropdown>
            </Menu>
            <Menu>
              <Menu.Target><Button variant="default" leftSection={<IconDownload size={16} />} data-testid="items-export">{tx("Export")}</Button></Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{data ? tx("Current view: {total} item(s)", { total: data.total }) : tx("Current view")}</Menu.Label>
                <Menu.Item component="a" href={downloadUrl(`/projects/${key}/export.xlsx${exportQs}`)} data-testid="export-xlsx">{tx("Excel (.xlsx)")}</Menu.Item>
                <Menu.Item component="a" href={downloadUrl(`/projects/${key}/export.csv${exportQs}`)} data-testid="export-csv">{tx("CSV")}</Menu.Item>
                <Menu.Divider />
                <Menu.Item component="a" href={downloadUrl(`/projects/${key}/reqif`)}>{tx("ReqIF (all requirements)")}</Menu.Item>
              </Menu.Dropdown>
            </Menu>
            {can("contributor") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-item">{tx("New item")}</Button>}
          </>
        } />
      <Card withBorder mb="sm" padding="sm">
        <QueryBar projectKey={key} value={query} onChange={(v) => setQuery(v)} fields={fields} />
      </Card>
      {selectionCount > 0 && (
        <Card withBorder mb="sm" padding="xs" className="bulk-bar" data-testid="bulk-bar">
          <Group justify="space-between" wrap="wrap" gap="xs">
            <Group gap="xs">
              <Text size="sm" fw={600} data-testid="bulk-count">{tx("{selectionCount} selected", { selectionCount: selectionCount })}</Text>
              {allOnPage && !allMatching && (data?.total ?? 0) > pageKeys.length && (
                <Button size="compact-xs" variant="subtle" onClick={() => setAllMatching(true)} data-testid="bulk-all">{tx("Select all {total} matching", { total: data?.total })}</Button>
              )}
              <Button size="compact-xs" variant="subtle" color="gray" onClick={() => { setSelected(new Set()); setAllMatching(false); }}>{tx("Clear")}</Button>
            </Group>
            <Group gap={6}>
              {can("contributor") && (
                <>
                  <Button size="xs" variant="light" leftSection={<IconEdit size={14} />} onClick={() => setBulk("update")} data-testid="bulk-edit">{tx("Edit fields")}</Button>
                  <Button size="xs" variant="light" leftSection={<IconRoute size={14} />} onClick={() => setBulk("transition")} data-testid="bulk-state">{tx("Change status")}</Button>
                  {model.releaseType && <Button size="xs" variant="light" leftSection={<IconTarget size={14} />} onClick={() => setBulk("plan")} data-testid="bulk-plan">{tx("Plan")}</Button>}
                  <Button size="xs" variant="light" leftSection={<IconLink size={14} />} onClick={() => setBulk("link")} data-testid="bulk-link-open">{tx("Link")}</Button>
                </>
              )}
              <Menu position="bottom-end">
                <Menu.Target><Button size="xs" variant="default" rightSection={<IconDots size={14} />} data-testid="bulk-more">{tx("More")}</Button></Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item leftSection={<IconEye size={14} />} onClick={() => setBulk("watch")} data-testid="bulk-watch">{tx("Watch")}</Menu.Item>
                  <Menu.Item leftSection={<IconEyeOff size={14} />} onClick={() => setBulk("unwatch")}>{tx("Stop watching")}</Menu.Item>
                  {model.releaseType && can("contributor") && <Menu.Item onClick={() => setBulk("unplan")}>{tx("Remove from a release…")}</Menu.Item>}
                  {can("manager") && <><Menu.Divider /><Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={() => setBulk("delete")} data-testid="bulk-delete">{tx("Move to recycle bin…")}</Menu.Item></>}
                </Menu.Dropdown>
              </Menu>
            </Group>
          </Group>
        </Card>
      )}
      <Grid gap="sm">
        <Grid.Col span={{ base: 12, lg: showPreview && previewKey ? 7 : 12 }}>
          <Card withBorder padding={0}>
            <Table.ScrollContainer minWidth={760}>
              <Table striped stickyHeader data-testid="items-table" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={34}>
                      <Checkbox size="xs" aria-label={tx("Select page")} checked={allOnPage} indeterminate={someOnPage && !allOnPage}
                        onChange={() => { setAllMatching(false); setSelected(allOnPage ? new Set() : new Set(pageKeys)); }} data-testid="select-page" />
                    </Table.Th>
                    {visible.map((c) => (
                      <Table.Th key={c.id} w={c.w}>
                        {c.sort ? (
                          <UnstyledButton onClick={() => sortBy(c)} className="th-sort" data-testid={`sort-${c.id}`}>
                            <Group gap={2} wrap="nowrap">{c.label}
                              {sort === c.sort && <IconArrowUp size={12} />}{sort === `-${c.sort}` && <IconArrowDown size={12} />}
                            </Group>
                          </UnstyledButton>
                        ) : c.label}
                      </Table.Th>
                    ))}
                    <Table.Th w={70}>
                      <Group gap={2} wrap="nowrap" justify="flex-end">
                        <ColumnChooser columns={columns} value={colIds} onChange={setCols} onReset={() => setCols(defaultCols)} />
                        <Tooltip label={showPreview ? tx("Preview pane on (click a row)") : tx("Preview pane off (rows open the item)")}>
                          <ActionIcon size="sm" variant={showPreview ? "light" : "subtle"} color="gray" data-testid="toggle-preview"
                            onClick={() => { const v = !showPreview; setShowPreview(v); writeStore("ariadne.items.preview", v); if (!v) setPreviewKey(null); }}
                            aria-label={tx("Preview pane")}><IconLayoutSidebarRight size={15} /></ActionIcon>
                        </Tooltip>
                      </Group>
                    </Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody style={{ opacity: isFetching ? 0.7 : 1 }}>
                  {data?.items.map((i) => (
                    <Table.Tr key={i.id} className={`clickable${previewKey === i.key ? " row-active" : ""}`} data-testid={`row-${i.key}`}
                      onClick={(e) => { if (!(e.target as HTMLElement).closest("a,button,input,label")) openRow(i); }}>
                      <Table.Td><Checkbox size="xs" aria-label={tx("Select {key}", { key: i.key })} checked={allMatching || selected.has(i.key)} onChange={() => toggle(i.key)} data-testid={`select-${i.key}`} /></Table.Td>
                      {visible.map((c) => <Table.Td key={c.id}>{c.render(i)}</Table.Td>)}
                      <Table.Td />
                    </Table.Tr>
                  ))}
                  {data && data.items.length === 0 && (
                    <Table.Tr><Table.Td colSpan={visible.length + 2}><Text c="dimmed" ta="center" py="lg">{tx("No items match.")}</Text></Table.Td></Table.Tr>
                  )}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
          {data && data.total > PAGE && (
            <Group justify="center" mt="md"><Pagination total={Math.ceil(data.total / PAGE)} value={page} onChange={setPage} /></Group>
          )}
        </Grid.Col>
        {showPreview && previewKey && (
          <Grid.Col span={{ base: 12, lg: 5 }}>
            <div className="preview-sticky"><ItemPreview projectKey={key} itemKey={previewKey} model={model} onClose={() => setPreviewKey(null)} /></div>
          </Grid.Col>
        )}
      </Grid>
      <ItemFormModal opened={creating} onClose={() => setCreating(false)} defaultType={singleType?.key} />
      <SaveViewModal opened={saving} onClose={() => setSaving(false)} query={{ q: query.q || undefined, conditions: query.conditions, sort, columns: colIds }} />
      <BulkModal projectKey={key} model={model} action={bulk} onClose={() => setBulk(null)}
        onDone={() => { setSelected(new Set()); setAllMatching(false); }}
        selection={allMatching ? { query: { q: query.q || undefined, conditions: query.conditions }, types: selectionTypes, count: selectionCount }
          : { keys: [...selected], types: selectionTypes, count: selectionCount }} />
    </>
  );
}

function ColumnChooser({ columns, value, onChange, onReset }: {
  columns: Record<string, Col>; value: string[]; onChange: (ids: string[]) => void; onReset: () => void;
}) {
  const [search, setSearch] = useState("");
  const all = Object.values(columns).filter((c) => c.label.toLowerCase().includes(search.toLowerCase()));
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);
  const move = (id: string, d: number) => {
    const i = value.indexOf(id), j = i + d;
    if (i < 0 || j < 0 || j >= value.length) return;
    const next = [...value]; [next[i], next[j]] = [next[j], next[i]]; onChange(next);
  };
  return (
    <Popover position="bottom-end" width={290} shadow="md">
      <Popover.Target>
        <Tooltip label={tx("Columns")}><ActionIcon size="sm" variant="subtle" color="gray" data-testid="columns-menu" aria-label={tx("Columns")}><IconColumns size={15} /></ActionIcon></Tooltip>
      </Popover.Target>
      <Popover.Dropdown data-testid="columns-chooser">
        <Stack gap={6}>
          <Text size="sm" fw={600}>{tx("Columns")}</Text>
          <TextInput size="xs" placeholder={tx("Find a column…")} value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
          <ScrollArea.Autosize mah={300}>
            <Stack gap={4}>
              {[...value.filter((id) => columns[id] && all.includes(columns[id])).map((id) => columns[id]), ...all.filter((c) => !value.includes(c.id))].map((c) => (
                <Group key={c.id} justify="space-between" wrap="nowrap">
                  <Checkbox size="xs" label={c.label} checked={value.includes(c.id)} onChange={() => toggle(c.id)} data-testid={`col-${c.id}`} />
                  {value.includes(c.id) && (
                    <Group gap={0} wrap="nowrap">
                      <ActionIcon size="xs" variant="subtle" color="gray" onClick={() => move(c.id, -1)} aria-label={tx("Move {label} left", { label: c.label })}><IconArrowUp size={11} /></ActionIcon>
                      <ActionIcon size="xs" variant="subtle" color="gray" onClick={() => move(c.id, 1)} aria-label={tx("Move {label} right", { label: c.label })}><IconArrowDown size={11} /></ActionIcon>
                    </Group>
                  )}
                </Group>
              ))}
            </Stack>
          </ScrollArea.Autosize>
          <Button size="compact-xs" variant="subtle" onClick={onReset}>{tx("Reset to default")}</Button>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}

function SaveViewModal({ opened, onClose, query }: { opened: boolean; onClose: () => void; query: Record<string, unknown> }) {
  const { key, can } = useProjectCtx();
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const save = useProjectMutation(key, () => api.post(`/projects/${key}/queries`, {
    name, shared, query: Object.fromEntries(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && !v.length))),
  }), { success: tx("View saved"), onSuccess: () => { setName(""); setShared(false); onClose(); } });
  return (
    <Modal opened={opened} onClose={onClose} title={tx("Save view")}>
      <Stack>
        <Text size="sm" c="dimmed">{tx("Saves the query (search and filters), the sort order and the columns.")}</Text>
        <TextInput label={tx("Name")} placeholder={tx("e.g. Unverified system requirements")} value={name} onChange={(e) => setName(e.currentTarget.value)} data-testid="view-name" />
        {can("contributor") && <Checkbox label={tx("Share with the project team")} checked={shared} onChange={(e) => setShared(e.currentTarget.checked)} data-testid="view-shared" />}
        <Group justify="flex-end"><Button onClick={() => save.mutate(undefined)} disabled={!name.trim()} loading={save.isPending} data-testid="view-save">{tx("Save")}</Button></Group>
      </Stack>
    </Modal>
  );
}
