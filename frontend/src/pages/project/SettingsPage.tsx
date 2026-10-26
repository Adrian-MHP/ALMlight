import { useState } from "react";
import {
  Accordion, ActionIcon, Alert, Anchor, Badge, Button, Card, Code, CopyButton, FileInput, Group, JsonInput, MultiSelect, NumberInput,
  Select, SimpleGrid, Stack, Switch, Table, Tabs, Text, TextInput, Title,
} from "@mantine/core";
import { IconDownload, IconTrash, IconUpload } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, downloadUrl } from "@/api/client";
import { useDirectory, useIntegrations, useMembers, useProjectMutation, useRecycleBin, useTemplateUpdates } from "@/api/hooks";
import type { ImportResult, Role } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { RepoList } from "@/components/RepoList";
import { CATEGORY_LABELS, stateColor } from "@/lib/model";
import { useProjectCtx } from "./ProjectLayout";
import { ReqifImport } from "./ReqifImport";
import { WordTemplates } from "./WordTemplates";
import { decimalSep, intlLocale, tx } from "@/lib/i18n";

export function SettingsPage() {
  const { can } = useProjectCtx();
  return (
    <>
      <PageHeader title={tx("Settings")} subtitle={tx("Team, information model, integrations and data exchange")} />
      <Tabs defaultValue={new URLSearchParams(window.location.search).get("tab") ?? "members"}>
        <Tabs.List mb="md">
          <Tabs.Tab value="members">{tx("Members")}</Tabs.Tab>
          <Tabs.Tab value="model" data-testid="tab-model">{tx("Information model")}</Tabs.Tab>
          {can("manager") && <Tabs.Tab value="integrations">{tx("Integrations")}</Tabs.Tab>}
          <Tabs.Tab value="io" data-testid="tab-io">{tx("Import / Export")}</Tabs.Tab>
          {can("manager") && <Tabs.Tab value="recycle" data-testid="tab-recycle">{tx("Recycle bin")}</Tabs.Tab>}
        </Tabs.List>
        <Tabs.Panel value="members"><Members /></Tabs.Panel>
        <Tabs.Panel value="model"><TemplateUpdatesBanner /><InformationModel /></Tabs.Panel>
        {can("manager") && <Tabs.Panel value="integrations"><IntegrationsView /></Tabs.Panel>}
        <Tabs.Panel value="io"><ImportExport /></Tabs.Panel>
        {can("manager") && <Tabs.Panel value="recycle"><RecycleBin /></Tabs.Panel>}
      </Tabs>
    </>
  );
}

const ROLES: { value: Role; label: string }[] = [
  { value: "viewer", label: tx("Viewer — read") },
  { value: "contributor", label: tx("Contributor — create & edit") },
  { value: "reviewer", label: tx("Reviewer — approve, baselines") },
  { value: "manager", label: tx("Manager — team, configuration") },
];

function Members() {
  const { key, can } = useProjectCtx();
  const members = useMembers(key).data ?? [];
  const users = useDirectory().data ?? [];
  const [user, setUser] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>("contributor");
  const set = useProjectMutation(key, (v: { user_id: string; role: string; hours_per_day?: number }) => api.put(`/projects/${key}/members`, v), { success: tx("Membership updated") });
  const remove = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/members/${id}`), { success: tx("Member removed") });
  const manager = can("manager");
  return (
    <Stack>
      {manager && (
        <Card withBorder padding="sm">
          <Group align="flex-end">
            <Select label={tx("User")} searchable value={user} onChange={setUser} w={260}
              data={users.filter((u) => !members.some((m) => m.user_id === u.id)).map((u) => ({ value: u.id, label: `${u.display_name} (${u.username})` }))} />
            <Select label={tx("Role")} data={ROLES} value={role} onChange={setRole} w={280} allowDeselect={false} />
            <Button disabled={!user} onClick={() => set.mutate({ user_id: user!, role: role! })}>{tx("Add member")}</Button>
          </Group>
        </Card>
      )}
      <Card withBorder padding={0}>
        <Table>
          <Table.Tbody>
            {members.map((m) => (
              <Table.Tr key={m.user_id}>
                <Table.Td><Text size="sm" fw={500}>{m.display_name}</Text><Text size="xs" c="dimmed">{m.username}{!m.active ? tx(" · inactive") : ""}</Text></Table.Td>
                <Table.Td w={300}>
                  {manager ? <Select size="xs" data={ROLES} value={m.role} allowDeselect={false} onChange={(r) => r && set.mutate({ user_id: m.user_id, role: r })} />
                    : <Badge variant="light">{m.role}</Badge>}
                </Table.Td>
                <Table.Td w={130}>
                  {manager ? (
                    <NumberInput size="xs" min={0} max={24} step={0.5} decimalScale={2} decimalSeparator={decimalSep()} suffix={tx(" h/day")} defaultValue={m.hours_per_day} key={`${m.user_id}-${m.hours_per_day}`}
                      aria-label={tx("Hours per day of {username}", { username: m.username })} data-testid={`member-hours-${m.username}`}
                      onBlur={(e) => { const v = parseFloat(e.currentTarget.value); if (Number.isFinite(v) && v !== m.hours_per_day) set.mutate({ user_id: m.user_id, role: m.role, hours_per_day: v }); }} />
                  ) : <Text size="sm" c="dimmed">{tx("{hours_per_day} h/day", { hours_per_day: m.hours_per_day })}</Text>}
                </Table.Td>
                <Table.Td w={50}>{manager && <ActionIcon variant="subtle" color="red" onClick={() => remove.mutate(m.user_id)}><IconTrash size={16} /></ActionIcon>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}

function InformationModel() {
  const { key, model, can, project } = useProjectCtx();
  const qc = useQueryClient();
  const [json, setJson] = useState<string | null>(null);
  const save = useProjectMutation(key, () => api.put(`/projects/${key}/config`, { config: JSON.parse(json!) }), {
    success: tx("Information model updated"), onSuccess: () => { setJson(null); qc.invalidateQueries({ queryKey: ["p", key, "config"] }); },
  });
  const cfg = model.config;
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {tx("Template")} <Code>{cfg.key}</Code> {tx("(version")} {project.config_version}{tx("). The information model is data: item types, fields, link types and workflows can be tailored per customer without code changes. Changes are checked against existing data.")}
      </Text>
      <Title order={5}>{tx("Item types")}</Title>
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {cfg.item_types.map((t) => (
          <Card key={t.key} withBorder padding="sm">
            <Group justify="space-between" mb={4}>
              <Text fw={600}>{t.label} <Text span c="dimmed" size="xs" className="mono">{t.prefix}-n</Text></Text>
              <Badge size="xs" variant="light">{CATEGORY_LABELS[t.category]}</Badge>
            </Group>
            {t.description && <Text size="xs" c="dimmed" mb={4}>{t.description}</Text>}
            <Group gap={4}>
              {t.fields.map((f) => <Badge key={f.key} size="xs" variant="outline" color="gray" style={{ textTransform: "none" }}>{f.label}: {f.type}{f.required ? "*" : ""}</Badge>)}
            </Group>
            <Text size="xs" mt={4}>{tx("Workflow: {workflow}{v}{v1}", { workflow: t.workflow ?? "—", v: t.change_controlled ? tx(" · change-controlled") : "", v1: t.document ? tx(" · document") : "" })}</Text>
          </Card>
        ))}
      </SimpleGrid>
      <Title order={5}>{tx("Link types")}</Title>
      <Card withBorder padding={0}>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>{tx("Link")}</Table.Th><Table.Th>{tx("From")}</Table.Th><Table.Th>{tx("To")}</Table.Th><Table.Th>{tx("Behaviour")}</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {cfg.link_types.map((l) => (
              <Table.Tr key={l.key}>
                <Table.Td><Text size="sm" fw={500}>{l.label}</Text><Text size="xs" c="dimmed">{tx("reverse: {reverse_label}", { reverse_label: l.reverse_label })}</Text></Table.Td>
                <Table.Td><Text size="xs">{l.sources.map((s) => (s === "*" ? "any" : model.typeLabel(s))).join(", ")}</Text></Table.Td>
                <Table.Td><Text size="xs">{l.targets.map((s) => (s === "*" ? "any" : model.typeLabel(s))).join(", ")}</Text></Table.Td>
                <Table.Td><Group gap={4}>
                  {l.structural && <Badge size="xs">{tx("structure")}</Badge>}
                  {l.acyclic && <Badge size="xs" variant="outline">{tx("acyclic")}</Badge>}
                  {l.suspect_on_target_change && <Badge size="xs" color="orange" variant="light">{tx("suspect on change")}</Badge>}
                </Group></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
      <Title order={5}>{tx("Workflows")}</Title>
      <Accordion variant="separated">
        {cfg.workflows.map((w) => (
          <Accordion.Item key={w.key} value={w.key}>
            <Accordion.Control>
              <Group gap="xs"><Text fw={500}>{w.label}</Text>
                {w.states.map((s) => <Badge key={s.key} size="xs" variant="light" color={stateColor(s.color, s.category)}>{s.label}</Badge>)}</Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Table>
                <Table.Tbody>
                  {w.transitions.map((t) => (
                    <Table.Tr key={t.key}>
                      <Table.Td><Text size="sm" fw={500}>{t.label}</Text></Table.Td>
                      <Table.Td><Text size="xs" className="mono">{t.from.join(", ")} → {t.to}</Text></Table.Td>
                      <Table.Td><Text size="xs">{tx("role ≥ {min_role}{v}{v1}{v2}", { min_role: t.min_role, v: t.approval ? tx(" · {count}× approval by {roles}{v}", { count: t.approval.count, roles: t.approval.roles.join("/"), v: t.approval.signature ? tx(" (e-signature)") : "" }) : "", v1: t.guards.length ? tx(" · guards: {guards}", { guards: t.guards.join(", ") }) : "", v2: t.effects.length ? tx(" · effects: {effects}", { effects: t.effects.join(", ") }) : "" })}</Text></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
      {can("manager") && (
        <Card withBorder>
          <Group justify="space-between" mb="xs">
            <Title order={5}>{tx("Advanced: edit as JSON")}</Title>
            {json === null ? <Button size="xs" variant="light" onClick={() => setJson(JSON.stringify(cfg, null, 2))}>{tx("Edit")}</Button>
              : <Group gap="xs"><Button size="xs" variant="default" onClick={() => setJson(null)}>{tx("Cancel")}</Button>
                <Button size="xs" onClick={() => save.mutate(undefined)} loading={save.isPending}>{tx("Validate & save")}</Button></Group>}
          </Group>
          {json !== null && <JsonInput value={json} onChange={setJson} autosize minRows={12} maxRows={30} validationError={tx("Invalid JSON")} formatOnBlur />}
        </Card>
      )}
    </Stack>
  );
}

function IntegrationsView() {
  const { key } = useProjectCtx();
  const data = useIntegrations(key).data;
  const [secret, setSecret] = useState<{ system: string; secret: string; endpoint: string } | null>(null);
  const [hookUrl, setHookUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["*"]);
  const [hookSecret, setHookSecret] = useState<string | null>(null);
  const configure = useProjectMutation(key, (v: { system: string; enabled: boolean; rotate_secret?: boolean }) =>
    api.put<{ secret: string | null; endpoint: string; system: string }>(`/projects/${key}/integrations/${v.system}`, v), {
    success: tx("Integration updated"), onSuccess: (r) => r.secret && setSecret({ system: r.system, secret: r.secret, endpoint: r.endpoint }),
  });
  const addHook = useProjectMutation(key, () => api.post<{ secret: string }>(`/projects/${key}/webhooks`, { url: hookUrl, events }), {
    success: tx("Webhook added"), onSuccess: (r) => { setHookSecret(r.secret); setHookUrl(""); },
  });
  const delHook = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/webhooks/${id}`), { success: tx("Webhook removed") });
  const inbound = (system: string) => data?.inbound.find((i) => i.system === system);
  return (
    <Stack>
      <Card withBorder data-testid="integration-repos">
        <Group justify="space-between" mb={4}>
          <Title order={5}>{tx("Git repositories")}</Title>
          <Button component={Link} to={`/p/${key}/code`} size="xs" variant="light">{tx("Manage on the Code page")}</Button>
        </Group>
        <Text size="xs" c="dimmed" mb="sm">{tx("Repositories are connected on the Code page and fetched regularly; the webhooks below make a push appear at once.")}</Text>
        <RepoList projectKey={key} />
      </Card>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {[{ system: "github", label: tx("GitHub"), help: tx("Repository → Settings → Webhooks: payload URL = endpoint, content type application/json, secret = shared secret, events: push, pull requests, workflow runs.") },
          { system: "azure_devops", label: tx("Azure DevOps"), help: tx("Project settings → Service hooks → Web Hooks: URL = endpoint, basic authentication with any user name and the shared secret as password. Events: code pushed, pull request, work item created/updated.") }]
          .map((s) => {
            const cfg = inbound(s.system);
            return (
              <Card withBorder key={s.system}>
                <Group justify="space-between" mb="xs">
                  <Text fw={600}>{s.label}</Text>
                  <Switch checked={!!cfg?.enabled} onChange={(e) => configure.mutate({ system: s.system, enabled: e.currentTarget.checked })} label={cfg?.enabled ? tx("enabled") : tx("off")} />
                </Group>
                <Text size="xs" c="dimmed" mb="xs">{tx("Item keys mentioned in commits, branches, pull requests or work items are linked automatically. {help}", { help: s.help })}</Text>
                {cfg && <Text size="xs">{tx("Endpoint:")} <Code>{cfg.endpoint}</Code></Text>}
                {cfg && <Button size="xs" variant="subtle" mt={4} onClick={() => configure.mutate({ system: s.system, enabled: true, rotate_secret: true })}>{tx("Generate new secret")}</Button>}
              </Card>
            );
          })}
      </SimpleGrid>
      {secret && (
        <Alert color="teal" title={tx("Shared secret for {system} — shown once", { system: secret.system })} withCloseButton onClose={() => setSecret(null)}>
          <Group gap="xs"><Code>{secret.secret}</Code><CopyButton value={secret.secret}>{({ copied, copy }) => <Button size="xs" onClick={copy}>{copied ? tx("Copied") : tx("Copy")}</Button>}</CopyButton></Group>
          <Text size="xs" mt={4}>{tx("Endpoint: {endpoint}", { endpoint: secret.endpoint })}</Text>
        </Alert>
      )}
      <Card withBorder>
        <Title order={5} mb="xs">{tx("Outbound webhooks")}</Title>
        <Text size="xs" c="dimmed" mb="sm">{tx("Ariadne POSTs domain events (JSON) to these URLs, signed with")} <Code>X-ALMlight-Signature: sha256=HMAC(secret, body)</Code>.</Text>
        <Group align="flex-end" mb="sm">
          <TextInput label={tx("URL")} placeholder={tx("https://…")} value={hookUrl} onChange={(e) => setHookUrl(e.currentTarget.value)} style={{ flex: 1 }} />
          <MultiSelect label={tx("Events")} data={["*", ...(data?.events ?? [])]} value={events} onChange={setEvents} w={300} />
          <Button onClick={() => addHook.mutate(undefined)} disabled={!hookUrl}>{tx("Add")}</Button>
        </Group>
        {hookSecret && <Alert color="teal" mb="sm" withCloseButton onClose={() => setHookSecret(null)} title={tx("Signing secret — shown once")}><Code>{hookSecret}</Code></Alert>}
        <Table>
          <Table.Tbody>
            {data?.webhooks.map((h) => (
              <Table.Tr key={h.id}>
                <Table.Td><Text size="sm">{h.url}</Text></Table.Td>
                <Table.Td><Text size="xs">{h.events.join(", ")}</Text></Table.Td>
                <Table.Td w={40}><ActionIcon variant="subtle" color="red" onClick={() => delHook.mutate(h.id)}><IconTrash size={16} /></ActionIcon></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}

function ImportExport() {
  const { key, model, can } = useProjectCtx();
  const [file, setFile] = useState<File | null>(null);
  const [defaultType, setDefaultType] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const run = useProjectMutation(key, (dryRun: boolean) => {
    const form = new FormData();
    form.append("file", file!);
    form.append("dry_run", String(dryRun));
    if (defaultType) form.append("default_type", defaultType);
    return api.upload<ImportResult>(`/projects/${key}/import`, form);
  }, {
    success: (r) => (r.applied ? tx("Import applied") : r.dry_run ? tx("Dry run complete") : tx("Import rejected — fix the errors")),
    onSuccess: (r) => setPreview(r),
  });
  return (
    <SimpleGrid cols={{ base: 1, lg: 2 }}>
      <Card withBorder>
        <Title order={5} mb="sm">{tx("Export")}</Title>
        <Stack gap="xs">
          <Anchor href={downloadUrl(`/projects/${key}/export.xlsx`)}><Group gap={6}><IconDownload size={16} />{tx("All items as Excel (.xlsx)")}</Group></Anchor>
          <Anchor href={downloadUrl(`/projects/${key}/export.csv`)}><Group gap={6}><IconDownload size={16} />{tx("All items as CSV")}</Group></Anchor>
          <Anchor href={downloadUrl(`/projects/${key}/reqif`)}><Group gap={6}><IconDownload size={16} />{tx("Requirements as ReqIF 1.2 (DOORS, Polarion, codebeamer, OEM portals)")}</Group></Anchor>
          <Text size="xs" c="dimmed">{tx("Documents: Word and PDF export from the document view (live or from a baseline), Word also in your corporate template.")}</Text>
          {can("manager") && <Anchor href={downloadUrl(`/projects/${key}/archive`)}><Group gap={6}><IconDownload size={16} />{tx("Full project archive (JSON with history, links, baselines)")}</Group></Anchor>}
        </Stack>
      </Card>
      {can("contributor") && (
        <Card withBorder>
          <Title order={5} mb="xs">{tx("Import from CSV / Excel")}</Title>
          <Text size="xs" c="dimmed" mb="sm">
            {tx("Columns:")} <Code>key, type, title, description, parent, applicability</Code>{tx(", one column per field key and per link type (target keys, comma-separated). Rows with an existing key update the item. Always run a dry run first — the import is all-or-nothing.")}
          </Text>
          <Stack>
            <FileInput label={tx("File")} accept=".csv,.xlsx" value={file} onChange={(f) => { setFile(f); setPreview(null); }} leftSection={<IconUpload size={16} />} data-testid="import-file" />
            <Select label={tx("Default type (rows without a type column)")} clearable value={defaultType} onChange={setDefaultType} data={model.typeOptions()} />
            <Group>
              <Button variant="light" disabled={!file} onClick={() => run.mutate(true)} loading={run.isPending && run.variables === true} data-testid="import-dry">{tx("Dry run")}</Button>
              <Button disabled={!file || !preview || !preview.dry_run || !!preview.summary.error} onClick={() => run.mutate(false)}
                loading={run.isPending && run.variables === false} data-testid="import-apply">{tx("Apply import")}</Button>
            </Group>
            {preview && (
              <Alert color={preview.summary.error ? "red" : preview.applied ? "green" : "blue"} title={preview.applied ? tx("Applied") : preview.dry_run ? tx("Dry run") : tx("Not applied")}>
                <Group gap={4} mb={4}>{Object.entries(preview.summary).map(([k, v]) => <Badge key={k} size="sm">{k}: {v}</Badge>)}</Group>
                {preview.results.filter((r) => r.action === "error").slice(0, 20).map((r, i) => <Text key={i} size="xs">{tx("Row {row}: {error}", { row: r.row, error: r.error })}</Text>)}
              </Alert>
            )}
          </Stack>
        </Card>
      )}
      {can("contributor") && <ReqifImport />}
      <WordTemplates />
    </SimpleGrid>
  );
}


function RecycleBin() {
  const { key } = useProjectCtx();
  const items = useRecycleBin(key).data ?? [];
  const restore = useProjectMutation(key, (itemKey: string) => api.post(`/projects/${key}/items/${itemKey}/undelete`),
    { success: tx("Item restored with its links and document position") });
  if (!items.length) return <Text c="dimmed">{tx("The recycle bin is empty. Deleted items appear here and can be restored with their links.")}</Text>;
  return (
    <Card withBorder padding={0}>
      <Table data-testid="recycle-table">
        <Table.Thead><Table.Tr><Table.Th>{tx("Item")}</Table.Th><Table.Th>{tx("Version")}</Table.Th><Table.Th>{tx("Deleted")}</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {items.map((i) => (
            <Table.Tr key={i.key}>
              <Table.Td><Text className="item-key" span>{i.key}</Text> <Text span size="sm">{i.title}</Text></Table.Td>
              <Table.Td><Text size="sm" className="mono">{i.version}</Text></Table.Td>
              <Table.Td><Text size="xs">{tx("{v} by {deleted_by}", { v: new Date(i.deleted_at).toLocaleString(intlLocale()), deleted_by: i.deleted_by ?? "?" })}</Text></Table.Td>
              <Table.Td w={100}><Button size="xs" variant="light" onClick={() => restore.mutate(i.key)} data-testid={`restore-${i.key}`}>{tx("Restore")}</Button></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}


/** Additions in the shipped template (new item types, fields, links, workflows) that this project can take over. */
function TemplateUpdatesBanner() {
  const { key, can } = useProjectCtx();
  const { data } = useTemplateUpdates(key);
  const apply = useProjectMutation(key, () => api.post(`/projects/${key}/template-updates`),
    { success: tx("Information model updated from the template") });
  if (!data || !data.count) return null;
  const parts = [
    data.item_types.length && tx("{length} item type(s): {item_types}", { length: data.item_types.length, item_types: data.item_types.map((t) => t.label).join(", ") }),
    data.fields.length && tx("{length} field(s): {fields}", { length: data.fields.length, fields: data.fields.map((f) => `${f.label} (${f.type})`).join(", ") }),
    data.link_types.length && tx("{length} link type(s): {link_types}", { length: data.link_types.length, link_types: data.link_types.map((l) => l.label).join(", ") }),
    data.link_attributes.length && tx("{length} link attribute(s)", { length: data.link_attributes.length }),
    data.workflows.length && tx("{length} workflow(s): {workflows}", { length: data.workflows.length, workflows: data.workflows.map((w) => w.label).join(", ") }),
    ...(data.translations ?? []).map((t) => tx("{count} label translation(s) ({locale})", { count: t.count, locale: t.locale })),
  ].filter(Boolean) as string[];
  return (
    <Alert color="blue" mb="md" title={tx("Template update available ({count} additions from “{template}” v{template_version})", { count: data.count, template: data.template, template_version: data.template_version })}
      data-testid="template-updates">
      <Stack gap={4}>
        {parts.map((p) => <Text key={p} size="sm">• {p}</Text>)}
        {data.skipped.map((p) => <Text key={p} size="xs" c="dimmed">{tx("Skipped: {p}", { p: p })}</Text>)}
        <Text size="xs" c="dimmed">{tx("Additions only: nothing existing is changed or removed.")}</Text>
        {can("manager") && <Group><Button size="xs" mt={4} onClick={() => apply.mutate(undefined)} loading={apply.isPending} data-testid="apply-template-updates">{tx("Take over the additions")}</Button></Group>}
      </Stack>
    </Alert>
  );
}
