import { useState } from "react";
import { Button, Card, Group, Menu, MultiSelect, Pagination, Select, Switch, Table, Text, TextInput } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconDownload, IconPlus, IconSearch } from "@tabler/icons-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { downloadUrl, qs } from "@/api/client";
import { useItems } from "@/api/hooks";
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
  const { data, isFetching } = useItems(key, {
    q: debouncedQ || undefined, type: type ? [type] : undefined, state: states.length ? states : undefined, suspect,
    sort: sort ?? "key", limit: PAGE, offset: (page - 1) * PAGE,
  });
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
            <Menu>
              <Menu.Target><Button variant="default" leftSection={<IconDownload size={16} />}>Export</Button></Menu.Target>
              <Menu.Dropdown>
                <Menu.Item component="a" href={downloadUrl(`/projects/${key}/export.xlsx${qs({ type: type ? [type] : undefined })}`)}>Excel (.xlsx)</Menu.Item>
                <Menu.Item component="a" href={downloadUrl(`/projects/${key}/export.csv${qs({ type: type ? [type] : undefined })}`)}>CSV</Menu.Item>
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
    </>
  );
}
