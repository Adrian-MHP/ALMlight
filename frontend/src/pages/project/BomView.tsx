import { useState } from "react";
import { ActionIcon, Badge, Button, Group, Menu, NumberInput, Popover, Select, Stack, Table, Text, TextInput } from "@mantine/core";
import { IconDownload, IconEdit } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { api, downloadUrl, qs } from "@/api/client";
import { useBom, useProjectMutation } from "@/api/hooks";
import type { BomRow } from "@/api/types";
import { useProjectCtx } from "./ProjectLayout";
import { tx } from "@/lib/i18n";

/** Multi-level bill of materials with find numbers, quantities (rolled up), units and effectivity. */
export function BomView({ rootKey }: { rootKey: string }) {
  const { key, can } = useProjectCtx();
  const [effective, setEffective] = useState<string>("");
  const { data } = useBom(key, rootKey, effective || null);
  const editable = can("contributor");
  return (
    <Stack gap="sm" data-testid="bom-view">
      <Group justify="space-between" wrap="wrap">
        <Group gap="xs">
          <TextInput type="date" size="xs" label={tx("Effective on")} value={effective} onChange={(e) => setEffective(e.currentTarget.value)}
            data-testid="bom-effective" />
          {effective && <Button size="compact-xs" variant="subtle" mt={18} onClick={() => setEffective("")}>{tx("all dates")}</Button>}
        </Group>
        <Menu>
          <Menu.Target><Button size="xs" variant="default" leftSection={<IconDownload size={14} />} data-testid="bom-export">{tx("Export BOM")}</Button></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item component="a" href={downloadUrl(`/projects/${key}/items/${rootKey}/bom.xlsx${qs({ effective: effective || null })}`)}>{tx("Excel (.xlsx)")}</Menu.Item>
            <Menu.Item component="a" href={downloadUrl(`/projects/${key}/items/${rootKey}/bom.csv${qs({ effective: effective || null })}`)}>{tx("CSV")}</Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>
      <Table.ScrollContainer minWidth={820}>
        <Table striped highlightOnHover data-testid="bom-table">
          <Table.Thead>
            <Table.Tr><Table.Th>{tx("Lvl")}</Table.Th><Table.Th>{tx("Find no.")}</Table.Th><Table.Th>{tx("Item")}</Table.Th><Table.Th>{tx("Rev")}</Table.Th><Table.Th>{tx("State")}</Table.Th>
              <Table.Th ta="right">{tx("Qty")}</Table.Th><Table.Th>{tx("Unit")}</Table.Th><Table.Th ta="right">{tx("Total")}</Table.Th><Table.Th>{tx("Effectivity")}</Table.Th><Table.Th /></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(data?.rows ?? []).map((r) => <BomLine key={r.link_id} row={r} editable={editable} />)}
            {data && data.rows.length === 0 && <Table.Tr><Table.Td colSpan={10}><Text c="dimmed" ta="center" py="md">{tx("No components{v}.", { v: effective ? tx(" effective on this date") : "" })}</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}

function BomLine({ row, editable }: { row: BomRow; editable: boolean }) {
  const { key } = useProjectCtx();
  const [open, setOpen] = useState(false);
  const [attrs, setAttrs] = useState({ quantity: row.quantity, unit: row.unit, find_number: row.find_number ?? "",
    effective_from: row.effective_from ?? "", effective_to: row.effective_to ?? "" });
  const save = useProjectMutation(key, () => api.patch(`/projects/${key}/links/${row.link_id}`, {
    attributes: { quantity: attrs.quantity, unit: attrs.unit, find_number: attrs.find_number || null,
      effective_from: attrs.effective_from || null, effective_to: attrs.effective_to || null },
  }), { success: tx("Updated {key} in the BOM", { key: row.key }), onSuccess: () => setOpen(false) });
  return (
    <Table.Tr data-testid={`bom-${row.key}`}>
      <Table.Td><Text size="xs" className="mono">{".".repeat(row.level)}{row.level}</Text></Table.Td>
      <Table.Td><Text size="sm" className="mono">{row.find_number ?? ""}</Text></Table.Td>
      <Table.Td style={{ paddingLeft: 8 + (row.level - 1) * 14 }}>
        <Link to={`/p/${row.project}/items/${row.key}`} className="item-key">{row.key}</Link> <Text span size="sm" fw={row.has_children ? 600 : undefined}>{row.title}</Text>
      </Table.Td>
      <Table.Td><Text size="xs" className="mono">{row.version}</Text></Table.Td>
      <Table.Td>{row.state && <Badge size="xs" variant="light" color={row.state_category === "released" ? "green" : "gray"}>{row.state}</Badge>}</Table.Td>
      <Table.Td ta="right"><Text size="sm">{row.quantity ?? 1}</Text></Table.Td>
      <Table.Td><Text size="sm">{row.unit ?? ""}</Text></Table.Td>
      <Table.Td ta="right"><Text size="sm" fw={600} data-testid={`bom-total-${row.key}`}>{row.total_quantity}</Text></Table.Td>
      <Table.Td><Text size="xs">{row.effective_from || row.effective_to ? `${row.effective_from ?? "…"} → ${row.effective_to ?? "…"}` : ""}</Text></Table.Td>
      <Table.Td w={40}>
        {editable && (
          <Popover opened={open} onChange={setOpen} position="left" withArrow shadow="md">
            <Popover.Target><ActionIcon size="sm" variant="subtle" onClick={() => setOpen((o) => !o)} data-testid={`bom-edit-${row.key}`}><IconEdit size={14} /></ActionIcon></Popover.Target>
            <Popover.Dropdown>
              <Stack gap="xs" w={240}>
                <Text size="sm" fw={600}>{tx("{key} in its parent", { key: row.key })}</Text>
                <NumberInput size="xs" label={tx("Quantity")} min={0} value={attrs.quantity ?? ""} onChange={(v) => setAttrs({ ...attrs, quantity: v === "" ? null : Number(v) })} data-testid="bom-qty" />
                <Select size="xs" label={tx("Unit")} clearable data={["pcs", "set", "m", "kg", "l"]} value={attrs.unit} onChange={(v) => setAttrs({ ...attrs, unit: v })} />
                <TextInput size="xs" label={tx("Find number")} value={attrs.find_number} onChange={(e) => setAttrs({ ...attrs, find_number: e.currentTarget.value })} />
                <TextInput size="xs" type="date" label={tx("Effective from")} value={attrs.effective_from} onChange={(e) => setAttrs({ ...attrs, effective_from: e.currentTarget.value })} />
                <TextInput size="xs" type="date" label={tx("Effective until")} value={attrs.effective_to} onChange={(e) => setAttrs({ ...attrs, effective_to: e.currentTarget.value })} />
                <Button size="xs" onClick={() => save.mutate(undefined)} loading={save.isPending} data-testid="bom-save">{tx("Save")}</Button>
              </Stack>
            </Popover.Dropdown>
          </Popover>
        )}
      </Table.Td>
    </Table.Tr>
  );
}
