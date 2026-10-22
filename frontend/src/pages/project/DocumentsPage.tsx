import { useState } from "react";
import { Badge, Button, Card, Group, SimpleGrid, Text } from "@mantine/core";
import { IconFileText, IconPlus } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { useItems } from "@/api/hooks";
import { StateBadge } from "@/components/badges";
import { PageHeader } from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";

export function DocumentsPage() {
  const { key, model, can } = useProjectCtx();
  const docTypes = model.documentTypes.map((t) => t.key);
  const { data } = useItems(key, { type: docTypes, limit: 200, sort: "key" }, docTypes.length > 0);
  const [creating, setCreating] = useState(false);
  return (
    <>
      <PageHeader title="Documents" subtitle="Live documents: specifications assembled from individually versioned and traceable items"
        actions={can("contributor") && docTypes.length > 0 && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-document">New document</Button>)} />
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {data?.items.map((d) => (
          <Card key={d.id} withBorder component={Link} to={`/p/${key}/documents/${d.key}`} style={{ textDecoration: "none" }} data-testid={`doc-${d.key}`}>
            <Group justify="space-between" mb={6}>
              <Group gap={6}><IconFileText size={18} /><Text className="item-key">{d.key}</Text></Group>
              <Group gap={4}><StateBadge item={d} /><Badge variant="default" className="mono">{d.version}</Badge></Group>
            </Group>
            <Text fw={600}>{d.title}</Text>
            <Text size="xs" c="dimmed" mt={4}>Updated {fmtRelative(d.updated_at)}</Text>
          </Card>
        ))}
      </SimpleGrid>
      {data?.items.length === 0 && <Text c="dimmed">No documents yet.</Text>}
      <ItemFormModal opened={creating} onClose={() => setCreating(false)} types={docTypes} defaultType={docTypes[0]} navigateOnCreate={false} />
    </>
  );
}
