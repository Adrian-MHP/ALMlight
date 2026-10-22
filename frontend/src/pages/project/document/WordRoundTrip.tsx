import { useState } from "react";
import { Alert, Badge, Button, FileInput, Group, Modal, Radio, Stack, Table, Text } from "@mantine/core";
import { IconFileTypeDocx, IconUpload } from "@tabler/icons-react";
import { api, downloadUrl } from "@/api/client";
import { useProjectMutation } from "@/api/hooks";
import type { WordImportResult } from "@/api/types";
import { useProjectCtx } from "../ProjectLayout";

const STATUS_COLORS: Record<string, string> = { updated: "green", conflict: "red", error: "red", frozen: "orange", missing: "gray" };

/** Export a review copy for external reviewers in Word (edit or comment only). */
export function WordReviewExport({ docKey, opened, onClose }: { docKey: string; opened: boolean; onClose: () => void }) {
  const { key } = useProjectCtx();
  const [mode, setMode] = useState("edit");
  return (
    <Modal opened={opened} onClose={onClose} title={`Word round trip — ${docKey}`}>
      <Stack>
        <Text size="sm" c="dimmed">
          Send the file to reviewers without access to Ariadne. Their edits and Word comments come back with “Import reviewed Word”
          and are applied as new versions (with history) — conflicting edits are reported, not overwritten.
        </Text>
        <Radio.Group value={mode} onChange={setMode}>
          <Stack gap="xs">
            <Radio value="edit" label="Reviewers may edit titles and texts (inside the marked fields) and comment" />
            <Radio value="comments" label="Reviewers may only comment (document protected)" />
          </Stack>
        </Radio.Group>
        <Group justify="flex-end">
          <Button component="a" href={downloadUrl(`/projects/${key}/items/${docKey}/export.docx?roundtrip=${mode}`)} onClick={onClose}
            leftSection={<IconFileTypeDocx size={16} />} data-testid="roundtrip-download">Download review copy</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Import a reviewed round-trip Word file: dry run first, then apply. */
export function WordImportDialog({ docKey, opened, onClose }: { docKey: string; opened: boolean; onClose: () => void }) {
  const { key } = useProjectCtx();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<WordImportResult | null>(null);
  const run = useProjectMutation(key, (dryRun: boolean) => {
    const form = new FormData();
    form.append("file", file!);
    form.append("dry_run", String(dryRun));
    return api.upload<WordImportResult>(`/projects/${key}/items/${docKey}/import-docx`, form);
  }, {
    success: (r) => (r.applied ? `Applied: ${r.summary.updated} updated, ${r.summary.comments} comments` : "Checked"),
    onSuccess: (r) => setResult(r),
  });
  return (
    <Modal opened={opened} onClose={() => { onClose(); setResult(null); setFile(null); }} title={`Import reviewed Word — ${docKey}`} size="xl">
      <Stack>
        <FileInput label="Reviewed .docx (exported as round-trip review copy)" accept=".docx" value={file} leftSection={<IconUpload size={16} />}
          onChange={(f) => { setFile(f); setResult(null); }} data-testid="word-file" />
        <Group>
          <Button variant="light" disabled={!file} onClick={() => run.mutate(true)} loading={run.isPending && run.variables === true} data-testid="word-check">Check changes</Button>
          <Button disabled={!file || !result || result.applied} onClick={() => run.mutate(false)} loading={run.isPending && run.variables === false} data-testid="word-apply">Apply</Button>
        </Group>
        {result && (
          <>
            <Alert color={result.applied ? "green" : "blue"} title={result.applied ? "Applied" : "Preview (nothing changed yet)"} data-testid="word-result">
              <Group gap={4}>{Object.entries(result.summary).map(([k, v]) => <Badge key={k} size="sm" variant="light">{k}: {v}</Badge>)}</Group>
            </Alert>
            {result.items.length > 0 && (
              <Table>
                <Table.Thead><Table.Tr><Table.Th>Item</Table.Th><Table.Th>Status</Table.Th><Table.Th>Change</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {result.items.map((i, n) => (
                    <Table.Tr key={n}>
                      <Table.Td><Text className="item-key">{i.key}</Text><Text size="xs">{i.base_version} → {i.new_version ?? i.current_version}</Text></Table.Td>
                      <Table.Td><Badge color={STATUS_COLORS[i.status] ?? "gray"} variant="light">{i.status}</Badge>
                        {i.conflicts && <Text size="xs" c="red">changed in Ariadne too: {i.conflicts.join(", ")}</Text>}</Table.Td>
                      <Table.Td>{(i.changes ?? []).map((c) => (
                        <Text key={c.field} size="xs"><b>{c.field}:</b> <span className="diff-del">{String(c.old).slice(0, 80)}</span> → <span className="diff-add">{String(c.new).slice(0, 80)}</span></Text>
                      ))}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
            {result.comments.length > 0 && (
              <Stack gap={2}>
                <Text size="sm" fw={600}>Comments from Word</Text>
                {result.comments.map((c, n) => <Text key={n} size="xs">{c.reply ? "↳ " : ""}<b>{c.author}</b> on {c.item}: {c.text}</Text>)}
              </Stack>
            )}
          </>
        )}
      </Stack>
    </Modal>
  );
}
