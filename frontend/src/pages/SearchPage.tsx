import { Badge, Card, Group, Stack, Text } from "@mantine/core";
import { Link, useSearchParams } from "react-router-dom";
import { useSearch } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";
import { tm, tx } from "@/lib/i18n";

export function SearchPage() {
  const [params] = useSearchParams();
  const q = params.get("q") ?? "";
  const { data = [], isLoading } = useSearch(q);
  return (
    <>
      <PageHeader title={tx("Search: “{q}”", { q: q })} subtitle={isLoading ? tx("Searching…") : tx("{length} result(s) across your projects", { length: data.length })} />
      <Stack gap="xs">
        {data.map((i) => (
          <Card key={i.id} withBorder padding="sm" component={Link} to={`/p/${i.project_key}/items/${i.key}`} style={{ textDecoration: "none" }}>
            <Group justify="space-between" wrap="nowrap">
              <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                <Badge variant="light">{i.project_key}</Badge>
                <Text className="item-key">{i.key}</Text>
                <Text size="sm" truncate>{i.title}</Text>
              </Group>
              <Group gap="xs" wrap="nowrap">
                {tm(i.lifecycle.label) && <Badge size="sm" variant="outline">{tm(i.lifecycle.label)}</Badge>}
                <Text size="xs" c="dimmed">{fmtRelative(i.updated_at)}</Text>
              </Group>
            </Group>
          </Card>
        ))}
      </Stack>
    </>
  );
}
