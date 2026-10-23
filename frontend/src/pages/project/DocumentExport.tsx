import { useState } from "react";
import { Button, Checkbox, Group, Menu, Modal, SegmentedControl, Select, Stack, Text } from "@mantine/core";
import { IconDownload, IconFileCode, IconFileImport, IconFileTypeDocx, IconFileTypePdf, IconMessages } from "@tabler/icons-react";
import { downloadUrl, qs } from "@/api/client";
import { useBaselines, useDocTemplates } from "@/api/hooks";
import { useProjectCtx } from "./ProjectLayout";
import { WordImportDialog, WordReviewExport } from "./document/WordRoundTrip";
import { tx } from "@/lib/i18n";

export interface DocView { at?: string | null; baseline?: string | null; variant?: string | null; numbering?: boolean }

/** Export a document (as currently viewed: live, as of a point in time, from a baseline, for a variant) and the Word round trip. */
export function DocumentExportMenu({ docKey, view = {} }: { docKey: string; view?: DocView }) {
  const [format, setFormat] = useState<"docx" | "pdf" | null>(null);
  const [review, setReview] = useState(false);
  const [importing, setImporting] = useState(false);
  const { key, can } = useProjectCtx();
  const live = !view.at && !view.baseline;
  return (
    <>
      <Menu position="bottom-end" width={260}>
        <Menu.Target><Button variant="default" leftSection={<IconDownload size={16} />} data-testid="doc-export">{tx("Export")}</Button></Menu.Target>
        <Menu.Dropdown>
          <Menu.Label>{live ? tx("Document") : tx("This historical state")}</Menu.Label>
          <Menu.Item leftSection={<IconFileTypeDocx size={16} />} onClick={() => setFormat("docx")} data-testid="export-docx">{tx("Word (.docx)…")}</Menu.Item>
          <Menu.Item leftSection={<IconFileTypePdf size={16} />} onClick={() => setFormat("pdf")} data-testid="export-pdf">{tx("PDF…")}</Menu.Item>
          <Menu.Item leftSection={<IconFileCode size={16} />} component="a" href={downloadUrl(`/projects/${key}/items/${docKey}/reqif`)}>{tx("ReqIF")}</Menu.Item>
          {live && can("contributor") && (
            <>
              <Menu.Divider />
              <Menu.Label>{tx("Word round trip")}</Menu.Label>
              <Menu.Item leftSection={<IconMessages size={16} />} onClick={() => setReview(true)} data-testid="export-review">{tx("Review copy for Word…")}</Menu.Item>
              <Menu.Item leftSection={<IconFileImport size={16} />} onClick={() => setImporting(true)} data-testid="import-review">{tx("Import reviewed Word…")}</Menu.Item>
            </>
          )}
        </Menu.Dropdown>
      </Menu>
      {format && <ExportDialog docKey={docKey} format={format} view={view} onClose={() => setFormat(null)} />}
      <WordReviewExport docKey={docKey} opened={review} onClose={() => setReview(false)} />
      <WordImportDialog docKey={docKey} opened={importing} onClose={() => setImporting(false)} />
    </>
  );
}

function ExportDialog({ docKey, format, view, onClose }: { docKey: string; format: "docx" | "pdf"; view: DocView; onClose: () => void }) {
  const { key } = useProjectCtx();
  const baselines = useBaselines(key).data ?? [];
  const [source, setSource] = useState(view.baseline ? "baseline" : view.at ? "at" : "live");
  const [baseline, setBaseline] = useState<string | null>(view.baseline ?? null);
  const [fields, setFields] = useState(true);
  const [links, setLinks] = useState(true);
  const templates = useDocTemplates(key).data ?? [];
  const [template, setTemplate] = useState<string | null>(null);
  const href = downloadUrl(`/projects/${key}/items/${docKey}/export.${format}${qs({
    baseline: source === "baseline" ? baseline : undefined, at: source === "at" ? view.at : undefined, variant: view.variant,
    numbering: view.numbering === false ? "false" : undefined, fields: String(fields), links: String(links),
    template: format === "docx" ? template : undefined,
  })}`);
  return (
    <Modal opened onClose={onClose} title={tx("Export {docKey} as {v}", { docKey: docKey, v: format === "docx" ? tx("Word") : tx("PDF") })}>
      <Stack>
        <SegmentedControl value={source} onChange={setSource}
          data={[{ value: "live", label: tx("Current state") }, { value: "baseline", label: tx("From a baseline") },
            ...(view.at ? [{ value: "at", label: tx("Viewed point in time") }] : [])]} />
        {source === "baseline" && (
          <Select label={tx("Baseline")} description={tx("The document exactly as frozen — e.g. the released specification for a customer")}
            data={baselines.map((b) => ({ value: b.id, label: `${b.name}${b.scope ? tx(" (scope {scope})", { scope: b.scope }) : ""}` }))}
            value={baseline} onChange={setBaseline} data-testid="export-baseline" />
        )}
        {view.variant && <Text size="sm">{tx("Variant specification for")} <b>{view.variant}</b> {tx("(non-applicable content omitted).")}</Text>}
        {format === "docx" && templates.length > 0 && (
          <Select label={tx("Layout")} description={tx("Your corporate Word template or the standard layout")} value={template ?? ""}
            onChange={(v) => setTemplate(v || null)} allowDeselect={false} data-testid="export-template"
            data={[{ value: "", label: tx("Standard layout") }, ...templates.map((t) => ({ value: t.id, label: t.name }))]} />
        )}
        <Checkbox label={tx("Include attributes (fields table per item)")} checked={fields} onChange={(e) => setFields(e.currentTarget.checked)} />
        <Checkbox label={tx("Include traceability (outgoing links)")} checked={links} onChange={(e) => setLinks(e.currentTarget.checked)} />
        <Text size="xs" c="dimmed">{template ? tx("Cover, headers and styles from the template; the document goes where the template says {{content}}.") : tx("Title page with version and state, table of contents, numbered headings, requirements with key, state and version.")}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button component="a" href={href} onClick={onClose} disabled={source === "baseline" && !baseline} data-testid="export-download">{tx("Download")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
