import { ActionIcon, Anchor, Card, FileButton, Button, Group, Table, Text, Tooltip } from "@mantine/core";
import { IconTrash, IconUpload } from "@tabler/icons-react";
import { api, downloadUrl } from "@/api/client";
import { useProjectMutation } from "@/api/hooks";
import type { ItemDetail } from "@/api/types";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";

export function AttachmentsTab({ item }: { item: ItemDetail }) {
  const { key, can } = useProjectCtx();
  const upload = useProjectMutation(key, (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.upload(`/projects/${key}/items/${item.key}/attachments`, form);
  }, { success: "File attached (new iteration)" });
  const remove = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/items/${item.key}/attachments/${id}`), { success: "File removed" });
  const editable = can("contributor") && !item.lifecycle.frozen;
  return (
    <>
      {editable && (
        <Group mb="md">
          <FileButton onChange={(f) => f && upload.mutate(f)}>
            {(props) => <Button {...props} leftSection={<IconUpload size={16} />} loading={upload.isPending} data-testid="upload">Attach file</Button>}
          </FileButton>
          <Text size="xs" c="dimmed">Files are versioned with the item and stored content-addressed (SHA-256).</Text>
        </Group>
      )}
      {item.attachments.length === 0 ? <Text c="dimmed">No files attached.</Text> : (
        <Card withBorder padding={0}>
          <Table>
            <Table.Tbody>
              {item.attachments.map((a) => (
                <Table.Tr key={a.id}>
                  <Table.Td><Anchor href={downloadUrl(`/projects/${key}/items/${item.key}/attachments/${a.id}`)} size="sm">{a.filename}</Anchor></Table.Td>
                  <Table.Td><Text size="xs">{a.content_type}</Text></Table.Td>
                  <Table.Td><Text size="xs">{fmtBytes(a.size)}</Text></Table.Td>
                  <Table.Td><Text size="xs" className="mono" c="dimmed">{a.sha256.slice(0, 12)}</Text></Table.Td>
                  <Table.Td><Text size="xs">{fmtDateTime(a.uploaded_at)}</Text></Table.Td>
                  <Table.Td w={40}>
                    {editable && <Tooltip label="Remove (kept in history)"><ActionIcon color="red" variant="subtle" onClick={() => remove.mutate(a.id)}><IconTrash size={16} /></ActionIcon></Tooltip>}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </>
  );
}
