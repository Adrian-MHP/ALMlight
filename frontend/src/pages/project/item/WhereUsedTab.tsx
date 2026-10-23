import { Badge, Card, Group, Stack, Text, Tooltip } from "@mantine/core";
import { IconChevronRight } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { useWhereUsed } from "@/api/hooks";
import type { ItemDetail } from "@/api/types";
import { useProjectCtx } from "../ProjectLayout";
import { tx } from "@/lib/i18n";

/** Every structure and document the item is used in — the paths up to the top (also in other projects). */
export function WhereUsedTab({ item }: { item: ItemDetail }) {
  const { key } = useProjectCtx();
  const { data } = useWhereUsed(key, item.key);
  if (!data) return null;
  return (
    <Card withBorder data-testid="where-used">
      <Text size="sm" mb="sm">{data.used_in ? tx("Used in {used_in} parent structure(s) / document(s)", { used_in: data.used_in }) : tx("Not used in any structure or document.")}</Text>
      <Stack gap={6}>
        {data.paths.map((path, i) => (
          <Group key={i} gap={4} wrap="wrap">
            {path.map((s, j) => (
              <Group key={j} gap={4} wrap="nowrap">
                <Link to={`/p/${s.project}/items/${s.key}`} className="item-key">{s.project !== key ? `${s.project}:` : ""}{s.key}</Link>
                <Text size="sm">{s.title}</Text>
                <IconChevronRight size={14} color="var(--mantine-color-dimmed)" />
                {s.quantity != null && <Tooltip label={tx("Quantity of {key} in {key1}", { key: path[j + 1]?.key ?? item.key, key1: s.key })}><Badge size="xs" variant="light">{s.quantity}×</Badge></Tooltip>}
              </Group>
            ))}
            <Text size="sm" fw={600} className="item-key">{item.key}</Text>
          </Group>
        ))}
      </Stack>
    </Card>
  );
}
