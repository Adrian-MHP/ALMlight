import { useState } from "react";
import {
  Alert, Anchor, Badge, Box, Breadcrumbs, Button, Card, Center, Grid, Group, Loader, Menu, Modal, Stack, Tabs, Text, TextInput, Title,
  Tooltip,
} from "@mantine/core";
import {
  IconArrowBackUp, IconDots, IconHistory, IconDownload, IconEdit, IconFileText, IconGitBranch, IconLock, IconSitemap, IconTrash,
} from "@tabler/icons-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, downloadUrl } from "@/api/client";
import { useItem, useItemApprovals, useLinks, useProjectMutation, useTransitions, useVersion } from "@/api/hooks";
import type { ItemDetail, TransitionOption, Version } from "@/api/types";
import { ApprovalCard } from "@/components/ApprovalCard";
import { StateBadge, TypeBadge } from "@/components/badges";
import { FieldsView } from "@/components/FieldsForm";
import { ItemPicker } from "@/components/ItemPicker";
import { RichText } from "@/components/rich/RichText";
import { LiveEditor, ParticipantAvatars } from "@/collab/LiveEditor";
import { useLive, usePresenceLocation } from "@/live/LiveProvider";
import { NotFound } from "@/components/NotFound";
import { ActionPrompt } from "@/components/PasswordPrompt";
import { fmtDateTime } from "@/lib/format";
import { CATEGORY_COLORS } from "@/lib/model";
import { useRemember } from "@/lib/recent";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";
import { LinksTab } from "./item/LinksTab";
import { HistoryTab } from "./item/HistoryTab";
import { ImpactTab } from "./item/ImpactTab";
import { AttachmentsTab } from "./item/AttachmentsTab";
import { CommentsTab } from "./item/CommentsTab";
import { DevelopmentTab } from "./item/DevelopmentTab";
import { VerificationTab } from "./item/VerificationTab";
import { RecordsTab } from "./item/RecordsTab";
import { StructureTree } from "./StructurePage";

export function ItemPage() {
  const { itemKey = "" } = useParams();
  const { key, model } = useProjectCtx();
  const { data: item, isLoading, isError } = useItem(key, itemKey.toUpperCase());
  const [vparams] = useSearchParams();
  const requested = vparams.get("version") ? Number(vparams.get("version")) : null;
  const viewVersion = useVersion(key, itemKey.toUpperCase(), requested).data ?? null;
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState(false);
  const live = useLive();
  usePresenceLocation(key, { item: item?.key ?? null, editing: editing && item ? item.key : null });
  useRemember(item ? { project: key, key: item.key, title: item.title, kind: "item" } : null);
  if (isLoading) return <Center mt={80}><Loader /></Center>;
  if (isError || !item) return <NotFound message={`Item ${itemKey} not found.`} />;
  const typeDef = model.type(item.type_key);
  const tab = params.get("tab") ?? "overview";
  const versionNo = params.get("version") && Number(params.get("version")) !== item.version_no ? Number(params.get("version")) : null;
  const sem = model.config.semantics;
  const verifiable = model.link(sem.verifies_link)?.targets.some((t) => t === "*" || t === item.type_key) ?? false;
  const isRun = sem.test_run_type === item.type_key;
  const hasStructure = model.config.link_types.some((lt) => lt.structural && lt.sources.includes(item.type_key));
  return (
    <>
      <Breadcrumbs mb="xs" separator="›">
        <Anchor component={Link} to={`/p/${key}`} size="sm">{key}</Anchor>
        <Anchor component={Link} to={`/p/${key}/items?type=${item.type_key}`} size="sm">{typeDef?.label ?? item.type_key}</Anchor>
        <Text size="sm" className="item-key">{item.key}</Text>
      </Breadcrumbs>
      <Group justify="space-between" align="flex-start" mb="sm" wrap="wrap" className="object-header">
        <Group gap="sm" align="flex-start" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
        <Box className="type-tile" style={{ background: `var(--mantine-color-${typeColor(typeDef?.color, typeDef?.category)}-7)` }}>
          {(typeDef?.label ?? item.type_key).slice(0, 2).toUpperCase()}
        </Box>
        <Stack gap={6} style={{ minWidth: 0, flex: 1 }}>
          <Group gap="xs">
            <Text className="item-key" size="lg" data-testid="item-key">{item.key}</Text>
            <TypeBadge typeKey={item.type_key} />
            <StateBadge item={item} size="md" />
            <Tooltip label="Revision.iteration — revisions are released generations, iterations are saves in between">
              <Badge variant="default" className="mono" data-testid="item-version">{item.version}</Badge>
            </Tooltip>
            {item.released_version && item.released_version !== item.version && (
              <Badge variant="light" color="green">released: {item.released_version}</Badge>
            )}
            {typeDef?.change_controlled && (
              <Tooltip label="Change-controlled: new revisions need a change order">
                <Badge variant="outline" color="orange" leftSection={<IconLock size={10} />}>change-controlled</Badge>
              </Tooltip>
            )}
            {item.change_order && (
              <Badge variant="light" color="orange" component={Link} to={`/p/${key}/items/${item.change_order}`} className="clickable">
                under {item.change_order}
              </Badge>
            )}
          </Group>
          <Title order={2} size="h3" data-testid="item-title-heading">{versionNo !== null && viewVersion ? viewVersion.title : item.title}</Title>
          <Group gap="xs">
            <Text size="xs" c="dimmed">
              Owner {item.owner?.display_name ?? "–"} · created {fmtDateTime(item.created_at)} by {item.created_by?.display_name ?? "–"} ·
              updated {fmtDateTime(item.updated_at)} by {item.updated_by?.display_name ?? "–"}
            </Text>
            <ParticipantAvatars size={20} people={uniqueUsers(live.presence(key).filter((u) => u.item === item.key || u.editing === item.key))} />
          </Group>
        </Stack>
        </Group>
        <WorkflowBar item={item} />
      </Group>
      {versionNo !== null && <VersionBanner item={item} versionNo={versionNo} version={viewVersion} />}
      <PendingApprovals itemKey={item.key} />
      <Tabs value={tab} onChange={(v) => { const p = new URLSearchParams(params); p.set("tab", v ?? "overview"); setParams(p, { replace: true }); }} keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="overview">Overview</Tabs.Tab>
          <Tabs.Tab value="links" data-testid="tab-links"><LinksTabLabel itemKey={item.key} /></Tabs.Tab>
          <Tabs.Tab value="impact" data-testid="tab-impact">Impact</Tabs.Tab>
          {hasStructure && <Tabs.Tab value="structure">Structure</Tabs.Tab>}
          {verifiable && <Tabs.Tab value="verification" data-testid="tab-verification">Verification</Tabs.Tab>}
          {isRun && <Tabs.Tab value="records" data-testid="tab-records">Test records</Tabs.Tab>}
          <Tabs.Tab value="history" data-testid="tab-history">History</Tabs.Tab>
          <Tabs.Tab value="approvals">Approvals</Tabs.Tab>
          <Tabs.Tab value="files">Files {item.attachments.length > 0 && <Badge size="xs" ml={4} circle>{item.attachments.length}</Badge>}</Tabs.Tab>
          <Tabs.Tab value="comments">Comments</Tabs.Tab>
          <Tabs.Tab value="development">Development</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview"><Overview item={item} version={versionNo !== null ? viewVersion : null} editing={editing} setEditing={setEditing} /></Tabs.Panel>
        <Tabs.Panel value="links"><LinksTab item={item} /></Tabs.Panel>
        <Tabs.Panel value="impact"><ImpactTab item={item} /></Tabs.Panel>
        {hasStructure && <Tabs.Panel value="structure"><Card withBorder><StructureTree rootKey={item.key} /></Card></Tabs.Panel>}
        {verifiable && <Tabs.Panel value="verification"><VerificationTab item={item} /></Tabs.Panel>}
        {isRun && <Tabs.Panel value="records"><RecordsTab item={item} /></Tabs.Panel>}
        <Tabs.Panel value="history"><HistoryTab item={item} /></Tabs.Panel>
        <Tabs.Panel value="approvals"><ApprovalsTab itemKey={item.key} /></Tabs.Panel>
        <Tabs.Panel value="files"><AttachmentsTab item={item} /></Tabs.Panel>
        <Tabs.Panel value="comments"><CommentsTab item={item} /></Tabs.Panel>
        <Tabs.Panel value="development"><DevelopmentTab item={item} /></Tabs.Panel>
      </Tabs>
    </>
  );
}

function typeColor(color?: string | null, category?: string | null): string {
  return color ?? CATEGORY_COLORS[category ?? "other"] ?? "gray";
}

function uniqueUsers(list: { user_id: string; name: string; color: string; editing: string | null }[]) {
  const m = new Map<string, { id: string; name: string; color: string; editing: boolean }>();
  for (const u of list) {
    const prev = m.get(u.user_id);
    m.set(u.user_id, { id: u.user_id, name: u.name, color: u.color, editing: (prev?.editing ?? false) || !!u.editing });
  }
  return Array.from(m.values());
}

function LinksTabLabel({ itemKey }: { itemKey: string }) {
  const { key } = useProjectCtx();
  const links = useLinks(key, itemKey).data ?? [];
  const suspects = links.filter((l) => l.suspect).length;
  return (
    <Group gap={4} wrap="nowrap">
      Links
      {links.length > 0 && <Badge size="xs" circle>{links.length}</Badge>}
      {suspects > 0 && <Badge size="xs" color="orange" circle>{suspects}</Badge>}
    </Group>
  );
}

function Overview({ item, version, editing, setEditing }: {
  item: ItemDetail; version?: Version | null; editing: boolean; setEditing: (v: boolean) => void;
}) {
  const { key, model, can } = useProjectCtx();
  const live = useLive();
  const defs = model.type(item.type_key)?.fields ?? [];
  const canWrite = can("contributor") && !item.lifecycle.frozen;
  const editors = live.presence(key).filter((u) => u.editing === item.key);
  if (version) item = { ...item, title: version.title, description: version.description, fields: version.fields, applicability: version.applicability };
  const texts = defs.filter((f) => f.type === "text" && item.fields[f.key]);
  return (
    <Grid>
      <Grid.Col span={{ base: 12, lg: 8 }}>
        <Card withBorder mb="md" className="text-card">
          {editing && !version ? (
            <LiveEditor target={item} projectKey={key} canWrite={canWrite} onClose={() => setEditing(false)} />
          ) : (
            <>
              <Group justify="space-between" mb={6}>
                <Group gap={6}>
                  <Text size="xs" c="dimmed" tt="uppercase" fw={600}>Text</Text>
                  {editors.length > 0 && (
                    <Badge size="xs" color="orange" variant="light" data-testid="item-editing-badge">
                      {editors.map((u) => u.name).join(", ")} editing live
                    </Badge>
                  )}
                </Group>
                {!version && (
                  <Button size="xs" variant="light" leftSection={<IconEdit size={14} />} onClick={() => setEditing(true)}
                    data-testid="edit-text">{canWrite ? (editors.length ? "Join live editing" : "Edit text") : "Live view"}</Button>
                )}
              </Group>
              <RichText html={item.description} testId="item-description-view" />
            </>
          )}
        </Card>
        {texts.map((f) => (
          <Card withBorder mb="md" key={f.key}>
            <Text size="xs" c="dimmed" mb={4}>{f.label}</Text>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{item.fields[f.key] as string}</Text>
          </Card>
        ))}
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 4 }}>
        <Card withBorder>
          <Stack gap="sm">
            <FieldsView defs={defs} values={item.fields} />
            <div>
              <Text size="xs" c="dimmed">Applicability</Text>
              {item.applicability ? <Text size="sm" className="mono" data-testid="value-applicability">{item.applicability}</Text>
                : <Text size="sm">All variants</Text>}
            </div>
          </Stack>
        </Card>
      </Grid.Col>
    </Grid>
  );
}

function PendingApprovals({ itemKey }: { itemKey: string }) {
  const { key } = useProjectCtx();
  const pending = (useItemApprovals(key, itemKey).data ?? []).filter((r) => r.status === "pending");
  if (!pending.length) return null;
  return <Stack gap="xs" mb="md">{pending.map((r) => <ApprovalCard key={r.id} req={r} showItem={false} />)}</Stack>;
}

function ApprovalsTab({ itemKey }: { itemKey: string }) {
  const { key } = useProjectCtx();
  const reqs = useItemApprovals(key, itemKey).data ?? [];
  if (!reqs.length) return <Text c="dimmed">No approvals requested yet.</Text>;
  return <Stack gap="xs">{reqs.map((r) => <ApprovalCard key={r.id} req={r} showItem={false} />)}</Stack>;
}

function WorkflowBar({ item }: { item: ItemDetail }) {
  const { key, model, can } = useProjectCtx();
  const navigate = useNavigate();
  const transitions = useTransitions(key, item.key).data ?? [];
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState<TransitionOption | null>(null);
  const [revising, setRevising] = useState(false);
  const typeDef = model.type(item.type_key);
  const run = useProjectMutation(key, (v: { t: string; comment: string; password: string }) =>
    api.post<{ status: string }>(`/projects/${key}/items/${item.key}/transitions/${v.t}`, { comment: v.comment || null, password: v.password || null }), {
    success: (r) => (r.status === "approval_requested" ? "Approval requested" : "State changed"),
    onSuccess: () => setPending(null),
  });
  const del = useProjectMutation(key, () => api.del(`/projects/${key}/items/${item.key}`), {
    success: `${item.key} deleted`, onSuccess: () => navigate(`/p/${key}/items`),
  });

  function start(t: TransitionOption) {
    if (t.comment_required || t.signature) setPending(t);
    else run.mutate({ t: t.key, comment: "", password: "" });
  }

  return (
    <Group gap="xs" wrap="wrap" data-testid="workflow-bar">
      {transitions.map((t) => {
        const tip = t.blocked_by.length ? t.blocked_by.join(" · ") : t.approval
          ? `Needs ${t.approval.count} approval(s) by ${t.approval.roles.join("/")}${t.approval.signature ? " with e-signature" : ""}`
          : `→ ${t.to_label}`;
        return (
          <Tooltip key={t.key} label={tip} multiline maw={320}>
            <Button size="sm" variant={t.approval ? "filled" : "light"} disabled={!t.allowed || !!t.pending_request_id}
              onClick={() => start(t)} loading={run.isPending && run.variables?.t === t.key} data-testid={`transition-${t.key}`}>
              {t.label}{t.pending_request_id ? " (pending)" : ""}
            </Button>
          </Tooltip>
        );
      })}
      {item.lifecycle.released && typeDef?.workflow && can("contributor") && (
        <Tooltip label="Start a new revision; the released revision stays valid until the new one is released">
          <Button size="sm" variant="light" color="orange" leftSection={<IconGitBranch size={16} />} onClick={() => setRevising(true)}
            data-testid="revise">Revise</Button>
        </Tooltip>
      )}
      {can("contributor") && (
        <Tooltip label={item.lifecycle.frozen ? `Frozen in state '${item.lifecycle.label}'` : "Edit title, attributes and applicability (creates a new iteration)"}>
          <Button size="sm" variant="default" leftSection={<IconEdit size={16} />} disabled={item.lifecycle.frozen}
            onClick={() => setEditing(true)} data-testid="edit-item">Properties</Button>
        </Tooltip>
      )}
      <Menu position="bottom-end">
        <Menu.Target><Button size="sm" variant="default" px={8}><IconDots size={16} /></Button></Menu.Target>
        <Menu.Dropdown>
          {typeDef?.document && <Menu.Item leftSection={<IconFileText size={16} />} component={Link} to={`/p/${key}/documents/${item.key}`}>Open document view</Menu.Item>}
          {model.config.link_types.some((lt) => lt.structural && lt.sources.includes(item.type_key)) &&
            <Menu.Item leftSection={<IconSitemap size={16} />} component={Link} to={`/p/${key}/structure?root=${item.key}`}>Open in structure</Menu.Item>}
          {typeDef?.document && <Menu.Item leftSection={<IconDownload size={16} />} component="a" href={downloadUrl(`/projects/${key}/items/${item.key}/export.docx`)}>Export Word</Menu.Item>}
          {typeDef?.document && <Menu.Item leftSection={<IconDownload size={16} />} component="a" href={downloadUrl(`/projects/${key}/items/${item.key}/export.pdf`)}>Export PDF</Menu.Item>}
          <Menu.Item leftSection={<IconDownload size={16} />} component="a" href={downloadUrl(`/projects/${key}/items/${item.key}/reqif`)}>Export ReqIF (sub-tree)</Menu.Item>
          {can("manager") && !item.released_version && (
            <Menu.Item color="red" leftSection={<IconTrash size={16} />} onClick={() => { if (confirm(`Delete ${item.key}?`)) del.mutate(undefined); }}>Delete</Menu.Item>
          )}
        </Menu.Dropdown>
      </Menu>
      <ItemFormModal opened={editing} onClose={() => setEditing(false)} item={item} />
      {pending && (
        <ActionPrompt opened onClose={() => setPending(null)} title={pending.label} signature={pending.signature}
          commentRequired={pending.comment_required} meaning={`${pending.label}: ${item.key} ${item.version} → ${pending.to_label}`}
          loading={run.isPending} onConfirm={(r) => run.mutate({ t: pending.key, comment: r.comment, password: r.password })} />
      )}
      <ReviseModal opened={revising} onClose={() => setRevising(false)} item={item} />
    </Group>
  );
}

function ReviseModal({ opened, onClose, item }: { opened: boolean; onClose: () => void; item: ItemDetail }) {
  const { key, model } = useProjectCtx();
  const [co, setCo] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const controlled = model.type(item.type_key)?.change_controlled;
  const coTypes = model.config.item_types.filter((t) => t.category === "change" &&
    model.workflow(t.key)?.states.some((s) => s.implementation_open)).map((t) => t.key);
  const revise = useProjectMutation(key, () => api.post(`/projects/${key}/items/${item.key}/revise`, { change_order: co, change_note: note || null }), {
    success: "New revision started", onSuccess: onClose,
  });
  return (
    <Modal opened={opened} onClose={onClose} title={`Revise ${item.key}`}>
      <Stack>
        <Text size="sm">
          Starts the next revision after {item.revision} in the initial lifecycle state. Revision {item.revision} stays the
          released configuration until the new revision is released.
        </Text>
        <ItemPicker label="Change order" types={coTypes} value={co} onChange={setCo} required={controlled}
          description={controlled ? "Required: the change order must be in work and list this item as affected." : "Optional"} testId="revise-co" />
        <TextInput label="Change note (optional)" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button leftSection={<IconArrowBackUp size={16} />} onClick={() => revise.mutate(undefined)} loading={revise.isPending}
            disabled={controlled && !co} data-testid="revise-confirm">Revise</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Read-only view of an older version (time travel for a single item). */
function VersionBanner({ item, versionNo, version }: { item: ItemDetail; versionNo: number; version: Version | null }) {
  const { key, can } = useProjectCtx();
  const navigate = useNavigate();
  const restore = useProjectMutation(key, () => api.post(`/projects/${key}/items/${item.key}/restore`, { version_no: versionNo, expected_version: item.version_no }),
    { success: "Restored as a new version", onSuccess: () => navigate(`/p/${key}/items/${item.key}?tab=history`) });
  const go = (n: number) => navigate(`/p/${key}/items/${item.key}?version=${n}`);
  return (
    <Alert color="violet" mb="md" icon={<IconHistory size={18} />} data-testid="version-banner"
      title={`Version ${version?.version ?? versionNo} — read-only (current: ${item.version})`}>
      <Group justify="space-between">
        <Text size="sm">{version ? `${version.kind} by ${version.created_by?.display_name ?? "?"} on ${fmtDateTime(version.created_at)}${version.change_note ? ` — ${version.change_note}` : ""}` : "Loading…"}</Text>
        <Group gap="xs">
          <Button size="xs" variant="default" disabled={versionNo <= 1} onClick={() => go(versionNo - 1)} data-testid="version-prev">← Older</Button>
          <Button size="xs" variant="default" disabled={versionNo >= item.version_no - 1} onClick={() => go(versionNo + 1)} data-testid="version-next">Newer →</Button>
          <Button size="xs" variant="light" onClick={() => navigate(`/p/${key}/items/${item.key}?tab=history&from=${versionNo}`)}>Compare with current</Button>
          {can("contributor") && !item.lifecycle.frozen && <Button size="xs" variant="light" color="orange" onClick={() => restore.mutate(undefined)} loading={restore.isPending}>Restore</Button>}
          <Button size="xs" onClick={() => navigate(`/p/${key}/items/${item.key}`)} data-testid="version-current">Current version</Button>
        </Group>
      </Group>
    </Alert>
  );
}
