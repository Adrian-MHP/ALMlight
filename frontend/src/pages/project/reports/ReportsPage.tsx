import { useState } from "react";
import { Badge, Button, Card, Group, Modal, SegmentedControl, Select, SimpleGrid, Stack, Text, Textarea, TextInput } from "@mantine/core";
import { IconChartBar, IconPlus } from "@tabler/icons-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useProjectMutation, useReports, useReportTemplates } from "@/api/hooks";
import type { Report } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { tx } from "@/lib/i18n";

/** Reports that users build themselves from widgets (like live reports in enterprise ALM tools). */
export function ReportsPage() {
  const { key, can } = useProjectCtx();
  const reports = useReports(key).data ?? [];
  const [creating, setCreating] = useState(false);
  return (
    <>
      <PageHeader title={tx("Reports")} subtitle={tx("Build your own reports from KPIs, charts, tables, trends and engineering KPIs — share them with the project or keep them private")}
        actions={can("contributor") && <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-report">{tx("New report")}</Button>} />
      {reports.length === 0 && <Text c="dimmed">{tx("No reports yet. Start from a template, e.g. “Project KPI overview”.")}</Text>}
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {reports.map((r) => (
          <Card key={r.id} withBorder component={Link} to={`/p/${key}/reports/${r.id}`} style={{ textDecoration: "none" }} data-testid={`report-${r.title}`}>
            <Group justify="space-between" mb={6}>
              <Group gap={6}><IconChartBar size={18} /><Text fw={600}>{r.title}</Text></Group>
              <Badge size="xs" variant="light" color={r.visibility === "private" ? "gray" : "indigo"}>{r.visibility}</Badge>
            </Group>
            <Text size="sm" c="dimmed" lineClamp={2}>{r.description || "—"}</Text>
            <Text size="xs" c="dimmed" mt="sm">{tx("{widget_count} widgets · {display_name} · updated {updated_at}", { widget_count: r.widget_count, display_name: r.owner?.display_name, updated_at: fmtRelative(r.updated_at) })}</Text>
          </Card>
        ))}
      </SimpleGrid>
      <CreateReport opened={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function CreateReport({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const { key } = useProjectCtx();
  const templates = useReportTemplates(key).data ?? [];
  const navigate = useNavigate();
  const [template, setTemplate] = useState<string | null>("kpi_overview");
  const [title, setTitle] = useState(tx("Project KPI overview"));
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState("project");
  const create = useProjectMutation(key, () => api.post<Report>(`/projects/${key}/reports`, {
    title, description: description || null, visibility, template: template === "blank" ? null : template,
  }), {
    success: tx("Report created"),
    onSuccess: (r) => { onClose(); navigate(`/p/${key}/reports/${r.id}${template === "blank" ? "?edit=1" : ""}`); },
  });
  return (
    <Modal opened={opened} onClose={onClose} title={tx("New report")}>
      <Stack>
        <Select label={tx("Start from")} data={[{ value: "blank", label: tx("Blank report") }, ...templates.map((t) => ({ value: t.key, label: t.title }))]}
          value={template} allowDeselect={false} data-testid="report-template"
          onChange={(v) => { setTemplate(v); const t = templates.find((x) => x.key === v); if (t) { setTitle(t.title); setDescription(t.description); } else setTitle(""); }} />
        <TextInput label={tx("Title")} value={title} onChange={(e) => setTitle(e.currentTarget.value)} required data-testid="report-title" />
        <Textarea label={tx("Description")} value={description} onChange={(e) => setDescription(e.currentTarget.value)} autosize minRows={2} />
        <SegmentedControl value={visibility} onChange={setVisibility} data={[{ value: "project", label: tx("Shared with project") }, { value: "private", label: tx("Private") }]} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button onClick={() => create.mutate(undefined)} disabled={!title.trim()} loading={create.isPending} data-testid="report-create">{tx("Create")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
