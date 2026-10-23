import { useEffect, useState } from "react";
import {
  ActionIcon, Badge, Button, Card, Center, Grid, Group, Loader, Menu, SegmentedControl, Stack, Text, Textarea, TextInput, Title, Tooltip,
} from "@mantine/core";
import { IconArrowDown, IconArrowUp, IconEdit, IconPlus, IconPrinter, IconTable, IconTrash } from "@tabler/icons-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, downloadUrl } from "@/api/client";
import { useMe, useProjectMutation, useReport, useReportData, useWidgetPreview } from "@/api/hooks";
import type { Report, ReportWidget } from "@/api/types";
import { NotFound } from "@/components/NotFound";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { WidgetEditor, WIDGET_TYPES, newWidget } from "./WidgetEditor";
import { WidgetView } from "./WidgetView";
import { tx } from "@/lib/i18n";

export function ReportView() {
  const { reportId = "" } = useParams();
  const { key, can } = useProjectCtx();
  const me = useMe().data!;
  const report = useReport(key, reportId);
  const [params, setParams] = useSearchParams();
  const editing = params.get("edit") === "1";
  const data = useReportData(key, reportId, !editing);
  const navigate = useNavigate();
  const [draft, setDraft] = useState<Report | null>(null);
  const [editingWidget, setEditingWidget] = useState<ReportWidget | null>(null);

  useEffect(() => { if (editing && report.data) setDraft(report.data); }, [editing, report.data]);

  const save = useProjectMutation(key, () => api.put(`/projects/${key}/reports/${reportId}`, {
    title: draft!.title, description: draft!.description, visibility: draft!.visibility, widgets: draft!.widgets,
  }), { success: tx("Report saved"), onSuccess: () => setParams({}) });
  const remove = useProjectMutation(key, () => api.del(`/projects/${key}/reports/${reportId}`), {
    success: tx("Report deleted"), onSuccess: () => navigate(`/p/${key}/reports`),
  });

  if (report.isLoading) return <Center mt={80}><Loader /></Center>;
  if (!report.data) return <NotFound message={tx("Report not found.")} />;
  const r = editing && draft ? draft : report.data;
  const canEdit = r.owner?.id === me.id || can("manager");
  const setWidgets = (widgets: ReportWidget[]) => setDraft((d) => (d ? { ...d, widgets } : d));

  function upsert(w: ReportWidget) {
    const list = draft!.widgets;
    setWidgets(list.some((x) => x.id === w.id) ? list.map((x) => (x.id === w.id ? w : x)) : [...list, w]);
    setEditingWidget(null);
  }

  function move(i: number, d: number) {
    const list = [...draft!.widgets];
    const [w] = list.splice(i, 1);
    list.splice(i + d, 0, w);
    setWidgets(list);
  }

  return (
    <>
      <Group justify="space-between" align="flex-start" mb="md" wrap="wrap">
        {editing && draft ? (
          <Stack gap="xs" style={{ flex: 1, maxWidth: 640 }}>
            <TextInput value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.currentTarget.value })} size="md" data-testid="report-title-edit" />
            <Textarea value={draft.description ?? ""} placeholder={tx("Description")} autosize minRows={1}
              onChange={(e) => setDraft({ ...draft, description: e.currentTarget.value })} />
            <SegmentedControl w={300} value={draft.visibility} onChange={(v) => setDraft({ ...draft, visibility: v as "project" | "private" })}
              data={[{ value: "project", label: tx("Shared") }, { value: "private", label: tx("Private") }]} />
          </Stack>
        ) : (
          <Stack gap={2}>
            <Group gap="xs"><Title order={2} size="h3" data-testid="report-heading">{r.title}</Title>
              <Badge size="sm" variant="light" color={r.visibility === "private" ? "gray" : "indigo"}>{r.visibility}</Badge></Group>
            {r.description && <Text c="dimmed" size="sm">{r.description}</Text>}
            <Text size="xs" c="dimmed">{tx("By {display_name} · updated {updated_at} · evaluated {fmtDateTime}", { display_name: r.owner?.display_name, updated_at: fmtDateTime(r.updated_at), fmtDateTime: fmtDateTime(new Date().toISOString()) })}</Text>
          </Stack>
        )}
        <Group gap="xs" className="no-print">
          {editing ? (
            <>
              <Menu position="bottom-end" width={320}>
                <Menu.Target><Button leftSection={<IconPlus size={16} />} variant="light" data-testid="add-widget">{tx("Add widget")}</Button></Menu.Target>
                <Menu.Dropdown>
                  {[tx("Basic"), tx("Engineering"), tx("Platform KPIs")].map((g) => (
                    <div key={g}>
                      <Menu.Label>{g}</Menu.Label>
                      {WIDGET_TYPES.filter((t) => t.group === g).map((t) => (
                        <Menu.Item key={t.value} onClick={() => setEditingWidget(newWidget(t.value))} data-testid={`add-${t.value}`}>
                          <Text size="sm">{t.label}</Text><Text size="xs" c="dimmed">{t.description}</Text>
                        </Menu.Item>
                      ))}
                    </div>
                  ))}
                </Menu.Dropdown>
              </Menu>
              <Button variant="default" onClick={() => { setParams({}); setDraft(null); }}>{tx("Cancel")}</Button>
              <Button onClick={() => save.mutate(undefined)} loading={save.isPending} data-testid="report-save">{tx("Save")}</Button>
            </>
          ) : (
            <>
              <Button variant="default" leftSection={<IconTable size={16} />} component="a" href={downloadUrl(`/projects/${key}/reports/${reportId}/export.xlsx`)}>{tx("Excel")}</Button>
              <Button variant="default" leftSection={<IconPrinter size={16} />} onClick={() => window.print()}>{tx("Print / PDF")}</Button>
              {canEdit && <Button leftSection={<IconEdit size={16} />} onClick={() => setParams({ edit: "1" })} data-testid="report-edit">{tx("Edit")}</Button>}
              {canEdit && <ActionIcon variant="subtle" color="red" size="lg" onClick={() => { if (confirm(tx("Delete this report?"))) remove.mutate(undefined); }}><IconTrash size={18} /></ActionIcon>}
            </>
          )}
        </Group>
      </Group>
      {r.widgets.length === 0 && <Text c="dimmed">{tx("This report has no widgets yet{v}", { v: editing ? tx(" — add one.") : "." })}</Text>}
      <Grid>
        {r.widgets.map((w, i) => (
          <Grid.Col key={w.id} span={{ base: 12, md: w.width ?? 6 }}>
            <Card withBorder h="100%" data-testid={`widget-${w.id}`} className="report-widget">
              <Group justify="space-between" mb="xs" wrap="nowrap">
                <Title order={6}>{w.title || WIDGET_TYPES.find((t) => t.value === w.type)?.label}</Title>
                {editing && (
                  <Group gap={2} wrap="nowrap">
                    <Tooltip label={tx("Move earlier")}><ActionIcon variant="subtle" size="sm" disabled={i === 0} onClick={() => move(i, -1)}><IconArrowUp size={14} /></ActionIcon></Tooltip>
                    <Tooltip label={tx("Move later")}><ActionIcon variant="subtle" size="sm" disabled={i === r.widgets.length - 1} onClick={() => move(i, 1)}><IconArrowDown size={14} /></ActionIcon></Tooltip>
                    <Tooltip label={tx("Configure")}><ActionIcon variant="subtle" size="sm" onClick={() => setEditingWidget(w)} data-testid={`configure-${w.id}`}><IconEdit size={14} /></ActionIcon></Tooltip>
                    <Tooltip label={tx("Remove")}><ActionIcon variant="subtle" size="sm" color="red" onClick={() => setWidgets(draft!.widgets.filter((x) => x.id !== w.id))}><IconTrash size={14} /></ActionIcon></Tooltip>
                  </Group>
                )}
              </Group>
              {editing ? <LiveWidget widget={w} /> : <WidgetView widget={w} data={data.data?.[w.id]} />}
            </Card>
          </Grid.Col>
        ))}
      </Grid>
      {editingWidget && <WidgetEditor initial={editingWidget} onSave={upsert} onClose={() => setEditingWidget(null)} />}
    </>
  );
}

function LiveWidget({ widget }: { widget: ReportWidget }) {
  const { key } = useProjectCtx();
  const preview = useWidgetPreview(key, widget);
  return <WidgetView widget={widget} data={preview.data} />;
}
