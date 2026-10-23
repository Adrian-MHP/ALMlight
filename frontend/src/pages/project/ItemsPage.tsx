import { useMemo, useState } from "react";
import { Badge, Button, Card, Checkbox, Group, Menu, Modal, MultiSelect, Pagination, Select, Stack, Switch, Table, Text, TextInput } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconBookmark, IconDeviceFloppy, IconDownload, IconPlus, IconSearch, IconTrash } from "@tabler/icons-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, downloadUrl, qs } from "@/api/client";
import { useItems, useProjectMutation, useSavedQueries } from "@/api/hooks";
import type { SavedQuery } from "@/api/types";
import { ItemLink, StateBadge, TypeBadge } from "@/components/badges";
import { PageHeader } from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";

const PAGE = 50;

export function ItemsPage() {
  const { key, model, can } = useProjectCtx();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const type = params.get("type");
  const [q, setQ] = useState(params.get("q") ?? "");
  const [debouncedQ] = useDebouncedValue(q, 300);
  const [states, setStates] = useState<string[]>([]);
  const [suspect, setSuspect] = useState(false);
  const [sort, setSort] = useState<string | null>("key");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [gap, setGap] = useState<string | null>(null);
  const [plannedIn, setPlannedIn] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const sem = model.config.semantics;
  const gaps = useMemo(() => [
    { value: "unverified", label: "Not verified by a test", link_type: sem.verifies_link, link_dir: "in" as const },
    { value: "underived", label: "Not derived from a parent requirement", link_type: sem.derives_link, link_dir: "out" as const },
    { value: "unallocated", label: "Not allocated (no satisfying element)", link_type: sem.satisfies_link, link_dir: "in" as const },
    { value: "unmitigated", label: "Risk without mitigation", link_type: sem.mitigation_link, link_dir: "out" as const },
    { value: "unplanned", label: "Not planned in a release", link_type: sem.planned_link, link_dir: "out" as const },
  ].filter((g) => model.link(g.link_type)), [model, sem]);
  const activeGap = gaps.find((g) => g.value === gap);
  const releases = useItems(key, { type: model.releaseType ? [model.releaseType.key] : [], limit: 100 }, !!model.releaseType).data?.items ?? [];
  const filter = {
    q: debouncedQ || undefined, type: type ? [type] : undefined, state: states.length ? states : undefined, suspect,
    sort: sort ?? "key", link_type: activeGap?.link_type, link_dir: activeGap?.link_dir, link_exists: activeGap ? false : undefined,
    planned_in: plannedIn ?? undefined,
  };
  const { data, isFetching } = useItems(key, { ...filter, limit: PAGE, offset: (page - 1) * PAGE });
  const exportFilter = { type: filter.type, q: filter.q, state: filter.state, suspect: filter.suspect || undefined,
    link_type: filter.link_type, link_dir: filter.link_dir, link_exists: filter.link_exists, planned_in: filter.planned_in };
  const views = useSavedQueries(key).data ?? [];
  const delView = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/queries/${id}`), { success: "View deleted" });

  function applyView(v: SavedQuery) {
    const q = v.query as Record<string, unknown>;
    const p = new URLSearchParams(params);
    const t = (q.type as string[] | undefined)?.[0];
    if (t) p.set("type", t); else p.delete("type");
    setParams(p);
    setQ((q.q as string) ?? "");
    setStates((q.state as string[]) ?? []);
    setSuspect(!!q.suspect);
    setSort((q.sort as string) ?? "key");
    setPlannedIn((q.planned_in as string) ?? null);
    setGap(q.link_type ? gaps.find((g) => g.link_type === q.link_type && g.link_dir === q.link_dir)?.value ?? null : null);
    setPage(1);
  }
  const stateOptions = type
    ? (model.workflow(type)?.states ?? []).map((s) => ({ value: s.key, label: s.label }))
    : Array.from(new Map(model.config.workflows.flatMap((w) => w.states).map((s) => [s.key, { value: s.key, label: s.label }])).values());
  const typeDef = type ? model.type(type) : undefined;
  const extraColumns = (typeDef?.fields ?? []).filter((f) => ["enum", "string", "boolean"].includes(f.type)).slice(0, 3);

  return (
    <>
      <PageHeader title={typeDef ? typeDef.label : "All items"} subtitle={data ? `${data.total} item(s)` : undefined}
        actions={
          <>
            <Menu position="bottom-end" width={300}>
              <Menu.Target><Button variant="default" leftSection={<IconBookmark size={16} />} data-testid="views-menu">Views{views.length ? ` (${views.length})` : ""}</Button></Menu.Target>
              <Menu.Dropdown>
                <Menu.Item leftSection={<IconDeviceFloppy size={14} />} onClick={() => setSaving(true)} data-testid="save-view">Save current filter as view…</Menu.Item>
                {views.length > 0 && <Menu.Divider />}
                {views.map((v) => (
                  <Menu.Item key={v.id} onClick={() => applyView(v)} data-testid={`view-${v.name}`}
                    rightSection={<Group gap={4} wrap="nowrap">
                      {v.count != null && <Badge size="xs" variant="light">{v.count}</Badge>}
                      {v.shared && <Badge size="xs" variant="outline" color="gray">shared</Badge>}
                      {v.can_edit && <IconTrash size={12} color="var(--mantine-color-red-6)" role="button" aria-label={`Delete view ${v.name}`}
                        data-testid={`view-delete-${v.name}`} onClick={(e) => { e.stopPropagation(); delView.mutate(v.id); }} />}
                    </Group>}>
                    {v.name}
                  </Menu.Item>
                ))}
              </Menu.Dropdown>
            </Menu>
            <Menu>
              <Menu.Target><Button variant="default" leftSection={<IconDownload size={16} />} data-testid="items-export">Export</Button></Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{data ? `Current view: ${data.total} item(s)` : "Current view"}</Menu.Label>
                <Menu.Item component="a" href={downloadUrl(`/projects/${key}/export.xlsx${qs(exportFilter)}`)} data-testid="export-xlsx">Excel (.xlsx)</Menu.Item>
                <Menu.Item component="a" href={downloadUrl(`/projects/${key}/export.csv${qs(exportFilter)}`)} data-testid="export-csv">CSV</Menu.Item>
                <Menu.Divider />
                <Menu.Item component="a" href={downloadUrl(`/projects/${key}/reqif`)}>ReqIF (all requirements)</Menu.Item>
              </Menu.Dropdown>
            </Menu>
            {can("contributor") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-item">New item</Button>}
          </>
        } />
      <Card withBorder mb="sm" padding="sm">
        <Group gap="sm" wrap="wrap">
          <TextInput placeholder="Search key, title, text…" leftSection={<IconSearch size={16} />} value={q}
            onChange={(e) => { setQ(e.currentTarget.value); setPage(1); }} w={260} data-testid="items-search" />
          <Select placeholder="All types" data={model.typeOptions()} value={type} clearable searchable w={240}
            onChange={(v) => { const p = new URLSearchParams(params); if (v) p.set("type", v); else p.delete("type"); setParams(p); setStates([]); setPage(1); }}
            data-testid="items-type-filter" />
          <MultiSelect placeholder="States" data={stateOptions} value={states} onChange={(v) => { setStates(v); setPage(1); }} w={240} clearable />
          <Select data={[{ value: "key", label: "Sort by key" }, { value: "-updated", label: "Recently updated" }, { value: "title", label: "Title" }, { value: "state", label: "State" }]}
            value={sort} onChange={setSort} w={180} allowDeselect={false} />
          {gaps.length > 0 && (
            <Select placeholder="Traceability gaps" data={gaps.map((g) => ({ value: g.value, label: g.label }))} value={gap} clearable w={270}
              onChange={(v) => { setGap(v); setPage(1); }} data-testid="items-gap-filter" />
          )}
          {model.releaseType && (
            <Select placeholder="Planned in" data={releases.map((r) => ({ value: r.key, label: `${r.key} — ${r.title}` }))} value={plannedIn}
              clearable w={210} onChange={(v) => { setPlannedIn(v); setPage(1); }} data-testid="items-release-filter" />
          )}
          <Switch label="Suspect links only" checked={suspect} onChange={(e) => { setSuspect(e.currentTarget.checked); setPage(1); }} />
        </Group>
      </Card>
      <Card withBorder padding={0}>
        <Table.ScrollContainer minWidth={800}>
          <Table striped stickyHeader data-testid="items-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={110}>Key</Table.Th>
                <Table.Th>Title</Table.Th>
                {!type && <Table.Th w={190}>Type</Table.Th>}
                {extraColumns.map((f) => <Table.Th key={f.key}>{f.label}</Table.Th>)}
                <Table.Th w={130}>State</Table.Th>
                <Table.Th w={80}>Version</Table.Th>
                <Table.Th w={150}>Owner</Table.Th>
                <Table.Th w={110}>Updated</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody style={{ opacity: isFetching ? 0.7 : 1 }}>
              {data?.items.map((i) => (
                <Table.Tr key={i.id} className="clickable" onClick={(e) => { if (!(e.target as HTMLElement).closest("a")) navigate(`/p/${key}/items/${i.key}`); }}>
                  <Table.Td><ItemLink item={i} /></Table.Td>
                  <Table.Td><Text size="sm" lineClamp={1}>{i.title}</Text></Table.Td>
                  {!type && <Table.Td><TypeBadge typeKey={i.type_key} /></Table.Td>}
                  {extraColumns.map((f) => {
                    const v = i.fields[f.key];
                    const label = f.type === "enum" ? f.options.find((o) => o.key === v)?.label ?? v : f.type === "boolean" ? (v ? "Yes" : "") : v;
                    return <Table.Td key={f.key}><Text size="sm">{(label as string) ?? ""}</Text></Table.Td>;
                  })}
                  <Table.Td><StateBadge item={i} /></Table.Td>
                  <Table.Td><Text size="sm" className="mono">{i.version}</Text></Table.Td>
                  <Table.Td><Text size="sm" truncate>{i.owner?.display_name ?? "–"}</Text></Table.Td>
                  <Table.Td><Text size="xs" c="dimmed">{fmtRelative(i.updated_at)}</Text></Table.Td>
                </Table.Tr>
              ))}
              {data && data.items.length === 0 && (
                <Table.Tr><Table.Td colSpan={9}><Text c="dimmed" ta="center" py="lg">No items match.</Text></Table.Td></Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>
      {data && data.total > PAGE && (
        <Group justify="center" mt="md"><Pagination total={Math.ceil(data.total / PAGE)} value={page} onChange={setPage} /></Group>
      )}
      <ItemFormModal opened={creating} onClose={() => setCreating(false)} defaultType={type ?? undefined} />
      <SaveViewModal opened={saving} onClose={() => setSaving(false)} query={{
        q: filter.q, type: filter.type, state: filter.state, suspect: filter.suspect || undefined, sort: filter.sort,
        link_type: filter.link_type, link_dir: filter.link_dir, link_exists: filter.link_exists, planned_in: filter.planned_in,
      }} />
    </>
  );
}

function SaveViewModal({ opened, onClose, query }: { opened: boolean; onClose: () => void; query: Record<string, unknown> }) {
  const { key, can } = useProjectCtx();
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const save = useProjectMutation(key, () => api.post(`/projects/${key}/queries`, {
    name, shared, query: Object.fromEntries(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== "")),
  }), { success: "View saved", onSuccess: () => { setName(""); setShared(false); onClose(); } });
  return (
    <Modal opened={opened} onClose={onClose} title="Save view">
      <Stack>
        <Text size="sm" c="dimmed">Saves the current search, type, states, traceability gap and release filter.</Text>
        <TextInput label="Name" placeholder="e.g. Unverified system requirements" value={name} onChange={(e) => setName(e.currentTarget.value)} data-testid="view-name" />
        {can("contributor") && <Checkbox label="Share with the project team" checked={shared} onChange={(e) => setShared(e.currentTarget.checked)} data-testid="view-shared" />}
        <Group justify="flex-end"><Button onClick={() => save.mutate(undefined)} disabled={!name.trim()} loading={save.isPending} data-testid="view-save">Save</Button></Group>
      </Stack>
    </Modal>
  );
}
