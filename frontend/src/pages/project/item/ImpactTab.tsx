import { Alert, Badge, Card, Group, Table, Text } from "@mantine/core";
import { useImpact } from "@/api/hooks";
import type { ItemDetail } from "@/api/types";
import { ItemLink, StateBadge, TypeBadge } from "@/components/badges";
import { useProjectCtx } from "../ProjectLayout";
import { tx } from "@/lib/i18n";

export function ImpactTab({ item }: { item: ItemDetail }) {
  const { key, model } = useProjectCtx();
  const { data } = useImpact(key, item.key);
  if (!data) return null;
  return (
    <>
      <Alert variant="light" mb="md" title={tx("{count} item(s) potentially affected by a change of {key}", { count: data.count, key: item.key })}>
        {tx("Everything that depends on this item along traceability links (derived requirements, allocated elements, verifying tests, …), plus the documents and assemblies that contain them.")}
        <Group gap={6} mt={6}>
          {Object.entries(data.by_type).map(([t, n]) => <Badge key={t} variant="light">{model.typeLabel(t)}: {n}</Badge>)}
        </Group>
      </Alert>
      <Card withBorder padding={0}>
        <Table data-testid="impact-table">
          <Table.Thead>
            <Table.Tr><Table.Th>{tx("Depth")}</Table.Th><Table.Th>{tx("Item")}</Table.Th><Table.Th>{tx("Type")}</Table.Th><Table.Th>{tx("State")}</Table.Th><Table.Th>{tx("Reached via")}</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data.impacted.map((r) => (
              <Table.Tr key={r.item.id}>
                <Table.Td w={60}><Badge variant="outline" color="gray">{r.depth}</Badge></Table.Td>
                <Table.Td><ItemLink item={r.item} withTitle /></Table.Td>
                <Table.Td><TypeBadge typeKey={r.item.type_key} /></Table.Td>
                <Table.Td><StateBadge item={r.item} /></Table.Td>
                <Table.Td>
                  <Text size="xs">
                    {r.relation === "where_used" ? tx("contains ") : `${model.link(r.via)?.label ?? r.via} `}
                    <span className="item-key">{r.via_item}</span>
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </>
  );
}
