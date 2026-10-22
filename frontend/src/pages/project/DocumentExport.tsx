import { useState } from "react";
import { Button, Checkbox, Group, Menu, Modal, SegmentedControl, Select, Stack, Text } from "@mantine/core";
import { IconDownload, IconFileTypeDocx, IconFileTypePdf, IconFileCode } from "@tabler/icons-react";
import { downloadUrl, qs } from "@/api/client";
import { useBaselines } from "@/api/hooks";
import { useProjectCtx } from "./ProjectLayout";

/** Export a live document as Word, PDF or ReqIF — or exactly as it was frozen in a baseline. */
export function DocumentExportMenu({ docKey }: { docKey: string }) {
  const [format, setFormat] = useState<"docx" | "pdf" | null>(null);
  const { key } = useProjectCtx();
  return (
    <>
      <Menu position="bottom-end">
        <Menu.Target><Button variant="default" leftSection={<IconDownload size={16} />} data-testid="doc-export">Export</Button></Menu.Target>
        <Menu.Dropdown>
          <Menu.Item leftSection={<IconFileTypeDocx size={16} />} onClick={() => setFormat("docx")} data-testid="export-docx">Word (.docx)…</Menu.Item>
          <Menu.Item leftSection={<IconFileTypePdf size={16} />} onClick={() => setFormat("pdf")} data-testid="export-pdf">PDF…</Menu.Item>
          <Menu.Item leftSection={<IconFileCode size={16} />} component="a" href={downloadUrl(`/projects/${key}/items/${docKey}/reqif`)}>ReqIF</Menu.Item>
        </Menu.Dropdown>
      </Menu>
      {format && <ExportDialog docKey={docKey} format={format} onClose={() => setFormat(null)} />}
    </>
  );
}

function ExportDialog({ docKey, format, onClose }: { docKey: string; format: "docx" | "pdf"; onClose: () => void }) {
  const { key } = useProjectCtx();
  const baselines = useBaselines(key).data ?? [];
  const [source, setSource] = useState("live");
  const [baseline, setBaseline] = useState<string | null>(null);
  const [fields, setFields] = useState(true);
  const [links, setLinks] = useState(true);
  const href = downloadUrl(`/projects/${key}/items/${docKey}/export.${format}${qs({
    baseline: source === "baseline" ? baseline : undefined, fields: String(fields), links: String(links),
  })}`);
  return (
    <Modal opened onClose={onClose} title={`Export ${docKey} as ${format === "docx" ? "Word" : "PDF"}`}>
      <Stack>
        <SegmentedControl value={source} onChange={setSource}
          data={[{ value: "live", label: "Current state" }, { value: "baseline", label: "From a baseline" }]} />
        {source === "baseline" && (
          <Select label="Baseline" description="The document exactly as frozen — e.g. the released specification for a customer"
            data={baselines.map((b) => ({ value: b.id, label: `${b.name}${b.scope ? ` (scope ${b.scope})` : ""}` }))}
            value={baseline} onChange={setBaseline} data-testid="export-baseline" />
        )}
        <Checkbox label="Include attributes (fields table per item)" checked={fields} onChange={(e) => setFields(e.currentTarget.checked)} />
        <Checkbox label="Include traceability (outgoing links)" checked={links} onChange={(e) => setLinks(e.currentTarget.checked)} />
        <Text size="xs" c="dimmed">Title page with version and state, table of contents, headings, requirements with key, state and version.</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button component="a" href={href} onClick={onClose} disabled={source === "baseline" && !baseline} data-testid="export-download">Download</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
