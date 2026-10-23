import { ActionIcon, Badge, Button, Card, Divider, Group, Loader, ScrollArea, Stack, Text, Tooltip } from "@mantine/core";
import { IconExternalLink, IconX } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { useItem, useLinks } from "@/api/hooks";
import { FieldsView } from "@/components/FieldsForm";
import { StateBadge, TypeBadge } from "@/components/badges";
import { RichText } from "@/components/rich/RichText";
import { WorkflowViewer } from "@/components/WorkflowViewer";
import { fmtDateTime } from "@/lib/format";
import type { Model } from "@/lib/model";
import { tm, tx } from "@/lib/i18n";

/** Read-only preview of an item beside the item list (Polarion split view). */
export function ItemPreview({ projectKey, itemKey, model, onClose }: { projectKey: string; itemKey: string; model: Model; onClose: () => void }) {
  const { data: item, isLoading } = useItem(projectKey, itemKey);
  const links = useLinks(projectKey, itemKey).data ?? [];
  if (isLoading || !item) return <Card withBorder><Loader size="sm" /></Card>;
  const t = model.type(item.type_key);
  const grouped = links.reduce<Record<string, typeof links>>((acc, l) => ({ ...acc, [tm(l.label)]: [...(acc[tm(l.label)] ?? []), l] }), {});
  return (
    <Card withBorder padding="sm" className="item-preview" data-testid="item-preview">
      <Group justify="space-between" wrap="nowrap" mb={4}>
        <Group gap={6} wrap="wrap">
          <Text className="item-key" fw={700}>{item.key}</Text>
          <TypeBadge typeKey={item.type_key} />
          <StateBadge item={item} size="xs" />
          <Badge size="xs" variant="outline" color="gray">{item.version}</Badge>
        </Group>
        <Group gap={2} wrap="nowrap">
          <Tooltip label={tx("Open")}><ActionIcon variant="subtle" component={Link} to={`/p/${projectKey}/items/${item.key}`} aria-label={tx("Open item")} data-testid="preview-open"><IconExternalLink size={16} /></ActionIcon></Tooltip>
          <ActionIcon variant="subtle" color="gray" onClick={onClose} aria-label={tx("Close preview")}><IconX size={16} /></ActionIcon>
        </Group>
      </Group>
      <Text fw={650} size="lg" mb={2}>{item.title}</Text>
      <Text size="xs" c="dimmed" mb="sm">{tx("{v}updated {updated_at}", { v: item.owner ? tx("Owner {display_name} · ", { display_name: item.owner.display_name }) : "", updated_at: fmtDateTime(item.updated_at) })}</Text>
      <ScrollArea.Autosize mah="calc(100vh - 330px)" type="auto">
        <Stack gap="sm">
          {t && <FieldsView defs={t.fields} values={item.fields} />}
          {item.description ? <RichText html={item.description} /> : <Text size="sm" c="dimmed" fs="italic">{tx("No description.")}</Text>}
          {Object.keys(grouped).length > 0 && (
            <>
              <Divider label={tx("Links")} labelPosition="left" />
              {Object.entries(grouped).map(([label, ls]) => (
                <div key={label}>
                  <Text size="xs" c="dimmed">{label}</Text>
                  {ls.map((l) => (
                    <Group key={l.id} gap={6} wrap="nowrap">
                      <Text component={Link} to={`/p/${projectKey}/items/${l.other.key}`} className="item-key" size="sm">{l.other.key}</Text>
                      <Text size="sm" truncate>{l.other.title}</Text>
                      {l.suspect && <Badge size="xs" color="orange">{tx("suspect")}</Badge>}
                    </Group>
                  ))}
                </div>
              ))}
            </>
          )}
          {t?.workflow && (
            <>
              <Divider label={tx("Workflow")} labelPosition="left" />
              <WorkflowViewer projectKey={projectKey} item={item} model={model} compact />
            </>
          )}
          <Button size="xs" variant="light" component={Link} to={`/p/${projectKey}/items/${item.key}`}>{tx("Open {key}", { key: item.key })}</Button>
        </Stack>
      </ScrollArea.Autosize>
    </Card>
  );
}
