import { useState } from "react";
import { ActionIcon, Alert, Anchor, Badge, Button, Card, Code, FileInput, Group, Stack, Table, Text, TextInput, Title, Tooltip } from "@mantine/core";
import { IconDownload, IconTemplate, IconTrash, IconUpload } from "@tabler/icons-react";
import { api, downloadUrl } from "@/api/client";
import { useDocTemplates, useProjectMutation } from "@/api/hooks";
import type { DocTemplateInfo } from "@/api/types";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { PRODUCT } from "@/lib/product";
import { useProjectCtx } from "./ProjectLayout";

/** Customer Word templates (corporate design) for document export. */
export function WordTemplates() {
  const { key, can } = useProjectCtx();
  const templates = useDocTemplates(key).data ?? [];
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const upload = useProjectMutation(key, () => {
    const form = new FormData();
    form.append("file", file!);
    form.append("name", name.trim());
    return api.upload<DocTemplateInfo>(`/projects/${key}/doc-templates`, form);
  }, { success: (t) => `Template “${t.name}” uploaded`, onSuccess: () => { setName(""); setFile(null); } });
  const remove = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/doc-templates/${id}`), { success: "Template deleted" });
  return (
    <Card withBorder data-testid="word-templates">
      <Group justify="space-between" mb="xs">
        <Title order={5}>Word templates</Title>
        <Anchor size="sm" href={downloadUrl(`/projects/${key}/doc-templates/sample.docx`)} data-testid="template-sample">
          <Group gap={4}><IconDownload size={14} />Sample template</Group>
        </Anchor>
      </Group>
      <Text size="xs" c="dimmed" mb="sm">
        Export documents in your corporate design: a .docx or .dotx with your page setup, styles, headers/footers and cover page.
        Placeholders <Code>{"{{title}}"}</Code> <Code>{"{{key}}"}</Code> <Code>{"{{version}}"}</Code> <Code>{"{{state}}"}</Code> <Code>{"{{project_name}}"}</Code> <Code>{"{{date}}"}</Code> <Code>{"{{author}}"}</Code> are
        filled; a paragraph with only <Code>{"{{toc}}"}</Code> becomes the table of contents, one with only <Code>{"{{content}}"}</Code> receives the document.
        Missing heading, list and table styles are added from the {PRODUCT} layout.
      </Text>
      {templates.length > 0 && (
        <Table mb="sm" data-testid="templates-table">
          <Table.Tbody>
            {templates.map((t) => (
              <Table.Tr key={t.id} data-testid={`template-${t.name}`}>
                <Table.Td>
                  <Group gap={6} wrap="nowrap"><IconTemplate size={16} /><Text size="sm" fw={600}>{t.name}</Text></Group>
                  <Text size="xs" c="dimmed">{t.filename} · {fmtBytes(t.size)} · {fmtDateTime(t.created_at)}{t.created_by ? ` · ${t.created_by.display_name}` : ""}</Text>
                </Table.Td>
                <Table.Td>
                  <Group gap={4}>
                    {t.has_content ? <Badge size="xs" color="teal" variant="light">content marker</Badge> : <Tooltip label="No {{content}} paragraph: the document is appended at the end"><Badge size="xs" color="yellow" variant="light">appends content</Badge></Tooltip>}
                    {t.has_toc && <Badge size="xs" variant="light">table of contents</Badge>}
                    {t.unknown.length > 0 && <Tooltip label={`Not filled: ${t.unknown.join(", ")}`}><Badge size="xs" color="orange" variant="light">{t.unknown.length} unknown</Badge></Tooltip>}
                  </Group>
                </Table.Td>
                <Table.Td w={80}>
                  <Group gap={2} wrap="nowrap">
                    <ActionIcon variant="subtle" component="a" href={downloadUrl(`/projects/${key}/doc-templates/${t.id}/download`)} aria-label="Download template"><IconDownload size={16} /></ActionIcon>
                    {can("manager") && <ActionIcon variant="subtle" color="red" onClick={() => remove.mutate(t.id)} aria-label="Delete template" data-testid={`template-delete-${t.name}`}><IconTrash size={16} /></ActionIcon>}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {templates.length === 0 && <Alert color="gray" mb="sm">No templates yet — documents export in the standard {PRODUCT} layout.</Alert>}
      {can("manager") && (
        <Stack gap="xs">
          <Group grow align="flex-end">
            <TextInput label="Name" placeholder="e.g. Customer specification" value={name} onChange={(e) => setName(e.currentTarget.value)} data-testid="template-name" />
            <FileInput label="Word file" accept=".docx,.dotx" value={file} onChange={setFile} leftSection={<IconUpload size={16} />} data-testid="template-file" />
          </Group>
          <Group justify="flex-end"><Button onClick={() => upload.mutate(undefined)} disabled={!file || !name.trim()} loading={upload.isPending} data-testid="template-upload">Upload template</Button></Group>
        </Stack>
      )}
    </Card>
  );
}
