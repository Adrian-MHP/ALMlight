import { useEffect, useMemo, useState } from "react";
import {
  ActionIcon, Alert, Anchor, Badge, Breadcrumbs, Button, Card, Center, Drawer, Group, Loader, Menu, Modal, MultiSelect, Select,
  Stack, Switch, Text, TextInput, Title, Tooltip,
} from "@mantine/core";
import {
  IconAlertTriangle, IconArrowBackUp, IconArrowDown, IconArrowUp, IconEdit, IconExternalLink, IconEye, IconGitBranch,
  IconGitCompare, IconHistory, IconLink, IconMessage, IconPlus, IconSearch,
} from "@tabler/icons-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { notifications } from "@mantine/notifications";
import { api } from "@/api/client";
import { useDocument, useFeatureModel, useItem, useMe, useProjectMutation, useThreads } from "@/api/hooks";
import type { DocNode, ItemDetail } from "@/api/types";
import { CommentThreads } from "@/components/CommentThreads";
import { ItemPicker } from "@/components/ItemPicker";
import { RichText } from "@/components/rich/RichText";
import { LiveEditor, ParticipantAvatars } from "@/collab/LiveEditor";
import { useLive, usePresenceLocation, type PresenceUser } from "@/live/LiveProvider";
import { NotFound } from "@/components/NotFound";
import { fmtDateTime } from "@/lib/format";
import { useRemember } from "@/lib/recent";
import { stateColor } from "@/lib/model";
import { BranchBar } from "./BranchMerge";
import { DocumentExportMenu } from "./DocumentExport";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";
import { CompareDialog } from "./document/CompareDialog";
import { DocBaselineButton, HistoryDrawer } from "./document/HistoryDrawer";

interface AddTarget { parent: string; position: number | null; existing?: boolean }
interface Filter { q: string; types: string[]; states: string[] }

function matches(n: DocNode, f: Filter): boolean {
  if (f.types.length && !f.types.includes(n.type_key)) return false;
  if (f.states.length && !f.states.includes(n.state_key ?? "")) return false;
  if (f.q) {
    const q = f.q.toLowerCase();
    const text = n.description.replace(/<[^>]+>/g, " ");
    if (!`${n.key} ${n.title} ${text}`.toLowerCase().includes(q)) return false;
  }
  return true;
}

/** Keep matching items and the headings that lead to them. */
function filterTree(nodes: DocNode[], f: Filter): DocNode[] {
  const active = f.q || f.types.length || f.states.length;
  if (!active) return nodes;
  const out: DocNode[] = [];
  for (const n of nodes) {
    const kids = filterTree(n.children, f);
    if (matches(n, f) || kids.length) out.push({ ...n, children: kids });
  }
  return out;
}

function count(nodes: DocNode[]): number {
  return nodes.reduce((s, n) => s + (n.is_heading ? 0 : 1) + count(n.children), 0);
}

/** Live document: an ordered outline of individually versioned items — live, at any point in history or from a baseline. */
export function DocumentView() {
  const { specKey = "" } = useParams();
  const docKey = specKey.toUpperCase();
  const { key, model, can } = useProjectCtx();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const at = params.get("at");
  const baseline = params.get("baseline");
  const variant = params.get("variant");
  const numbering = params.get("numbering") !== "false";
  const historical = !!(at || baseline);
  const doc = useDocument(key, docKey, { at, baseline, variant, numbering });
  const spec = useItem(key, docKey);
  const variants = useFeatureModel(key).data?.variants ?? [];
  const [filter, setFilter] = useState<Filter>({ q: "", types: [], states: [] });
  const [adding, setAdding] = useState<AddTarget | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [commentsFor, setCommentsFor] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [branching, setBranching] = useState(false);
  const editItem = useItem(key, editing ?? "", !!editing);
  const [liveBlock, setLiveBlock] = useState<string | null>(null);
  const live = useLive();
  const me = useMe().data;
  usePresenceLocation(key, { doc: docKey, editing: liveBlock });
  useRemember(doc.data && !historical ? { project: key, key: docKey, title: doc.data.root.title, kind: "document" } : null);
  const here = live.presence(key).filter((u) => u.doc === docKey);
  const docItemIds = useMemo(() => {
    const ids = new Set<string>();
    const walk = (nodes: DocNode[]) => nodes.forEach((n) => { ids.add(n.item_id); walk(n.children); });
    if (doc.data) { ids.add(doc.data.root.item_id); walk(doc.data.root.children); }
    return ids;
  }, [doc.data]);
  useEffect(() => live.onChange((e) => {
    if (!me || e.actor_id === me.id || e.project !== key) return;
    const hit = (e.entity_id && docItemIds.has(e.entity_id)) || e.related_ids.some((r) => docItemIds.has(r));
    if (hit) notifications.show({ title: `${e.actor} changed the document`, message: e.summary, color: "blue", autoClose: 5000 });
  }), [live, docItemIds, me, key]);

  const setParam = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v); else p.delete(k);
    setParams(p);
  };
  const tree = useMemo(() => filterTree(doc.data?.root.children ?? [], filter), [doc.data, filter]);
  const total = useMemo(() => count(doc.data?.root.children ?? []), [doc.data]);

  if (doc.isLoading || spec.isLoading) return <Center mt={80}><Loader /></Center>;
  if (doc.isError) {
    return (
      <Alert color={historical ? "violet" : "red"} icon={<IconHistory size={18} />} mt="md" maw={720} mx="auto"
        title={historical ? "Not available in this state" : "The document could not be opened"} data-testid="doc-error">
        <Text size="sm" mb="sm">{doc.error?.message}{historical
          ? " — the baseline or point in time does not contain this document (it was created later or is outside the baseline's scope)." : ""}</Text>
        <Group gap="xs">
          <Button size="xs" onClick={() => navigate(`/p/${key}/documents/${docKey}`)}>Open the live document</Button>
          {historical && <Button size="xs" variant="default" onClick={() => navigate(`/p/${key}/baselines`)}>Baselines</Button>}
        </Group>
      </Alert>
    );
  }
  if (!doc.data || !spec.data) return <NotFound />;
  const root = doc.data.root;
  const editable = !historical && can("contributor") && !spec.data.lifecycle.frozen;
  const childTypes = model.config.link_types.filter((lt) => lt.structural)
    .flatMap((lt) => (lt.sources.includes(spec.data!.type_key) || lt.sources.includes("heading") ? lt.targets : []));
  const allowedTypes = Array.from(new Set(childTypes)).filter((t) => model.type(t) && !model.type(t)!.document);
  const stateOptions = Array.from(new Map(model.config.workflows.flatMap((w) => w.states).map((s) => [s.key, { value: s.key, label: s.label }])).values());
  const shown = count(tree);
  const filtering = !!(filter.q || filter.types.length || filter.states.length);

  return (
    <>
      <Breadcrumbs mb="xs" separator="›">
        <Anchor component={Link} to={`/p/${key}/documents`} size="sm">Documents</Anchor>
        <Text size="sm" className="item-key">{docKey}</Text>
      </Breadcrumbs>
      <Group justify="space-between" mb="sm" align="flex-start" wrap="wrap">
        <Stack gap={4}>
          <Group gap="xs">
            <Title order={2} size="h3" data-testid="document-title">{root.title}</Title>
            {root.state && <Badge variant="light" color={stateColor(root.state_color, root.state_category)}>{root.state}</Badge>}
            <Badge variant="default" className="mono">{root.version}</Badge>
          </Group>
          <Text size="xs" c="dimmed">Each block is an item with its own version, workflow and traceability. Release the document once all items are approved.</Text>
        </Stack>
        <Group gap="xs">
          <PresenceBar people={here} meId={me?.id} />
          <Button variant="default" leftSection={<IconHistory size={16} />} onClick={() => setHistoryOpen(true)} data-testid="doc-history">History</Button>
          <Button variant="default" leftSection={<IconGitCompare size={16} />} onClick={() => setCompareOpen(true)} data-testid="doc-compare">Compare</Button>
          {!historical && <DocBaselineButton docKey={docKey} />}
          <DocumentExportMenu docKey={docKey} view={{ at, baseline, variant, numbering }} />
          <Button variant="default" leftSection={<IconMessage size={16} />} onClick={() => setCommentsFor("__doc__")} data-testid="doc-comments">Comments</Button>
          <Menu position="bottom-end">
            <Menu.Target><Button variant="default" px={10} data-testid="doc-more">…</Button></Menu.Target>
            <Menu.Dropdown>
              <Menu.Item leftSection={<IconExternalLink size={16} />} component={Link} to={`/p/${key}/items/${docKey}`}>Document item (workflow, approvals)</Menu.Item>
              {can("contributor") && !historical && <Menu.Item leftSection={<IconGitBranch size={16} />} onClick={() => setBranching(true)} data-testid="create-branch">Branch document…</Menu.Item>}
            </Menu.Dropdown>
          </Menu>
          {editable && (
            <Menu position="bottom-end">
              <Menu.Target><Button leftSection={<IconPlus size={16} />} data-testid="doc-add">Add</Button></Menu.Target>
              <Menu.Dropdown>
                <Menu.Item onClick={() => setAdding({ parent: docKey, position: null })} data-testid="doc-add-new">New item at the end</Menu.Item>
                <Menu.Item onClick={() => setAdding({ parent: docKey, position: null, existing: true })} leftSection={<IconLink size={14} />}>Insert existing item (reuse)</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          )}
        </Group>
      </Group>

      {historical && (
        <Alert color="violet" icon={<IconHistory size={18} />} mb="md" data-testid="history-banner"
          title={baseline ? `Baseline “${doc.data.baseline?.name}” — read-only` : `As of ${fmtDateTime(at)} — read-only`}>
          <Group justify="space-between">
            <Text size="sm">The document exactly as it was{baseline ? ` when the baseline was taken (${fmtDateTime(doc.data.baseline?.created_at)})` : ""}: texts, versions, states and outline.</Text>
            <Group gap="xs">
              <Button size="xs" variant="light" leftSection={<IconGitCompare size={14} />}
                onClick={() => navigate(`/p/${key}/documents/${docKey}/compare?${baseline ? `l_bl=${baseline}` : `l_at=${encodeURIComponent(at!)}`}`)}
                data-testid="compare-with-live">Compare with live</Button>
              <Button size="xs" onClick={() => navigate(`/p/${key}/documents/${docKey}${variant ? `?variant=${variant}` : ""}`)} data-testid="back-to-live">Back to live</Button>
            </Group>
          </Group>
        </Alert>
      )}

      <Card withBorder padding="xs" mb="sm">
        <Group gap="sm" wrap="wrap">
          <TextInput size="xs" placeholder="Filter text…" leftSection={<IconSearch size={14} />} value={filter.q} w={200}
            onChange={(e) => setFilter({ ...filter, q: e.currentTarget.value })} data-testid="doc-filter" />
          <MultiSelect size="xs" placeholder="Types" w={200} data={model.typeOptions((t) => allowedTypes.includes(t.key))} value={filter.types}
            onChange={(v) => setFilter({ ...filter, types: v })} clearable />
          <MultiSelect size="xs" placeholder="States" w={180} data={stateOptions} value={filter.states} onChange={(v) => setFilter({ ...filter, states: v })} clearable />
          <Select size="xs" placeholder="All variants (150%)" w={230} clearable value={variant} onChange={(v) => setParam("variant", v)}
            data={variants.map((v) => ({ value: v.key, label: `${v.key} — ${v.title}` }))} data-testid="doc-variant" />
          <Switch size="xs" label="Numbered headings" checked={numbering} onChange={(e) => setParam("numbering", e.currentTarget.checked ? null : "false")} />
          {shown !== total && <Badge variant="light" data-testid="filter-count">{shown} of {total} items</Badge>}
          {doc.data.variant && <Badge color="pink" variant="light">Variant {doc.data.variant.key}</Badge>}
        </Group>
      </Card>

      {!historical && <BranchBar docKey={docKey} creating={branching} onCloseCreate={() => setBranching(false)} />}

      <Card withBorder padding="xl" className="doc-paper" data-testid="document">
        {root.description && <div style={{ marginBottom: 12 }}><RichText html={root.description} empty="" /></div>}
        {tree.length === 0 && <Text c="dimmed">{total ? "Nothing matches the filter." : "This document is empty. Add headings and requirements."}</Text>}
        <Blocks nodes={tree} depth={0} parentKey={docKey} editable={editable && !filtering}
          historical={historical} onAdd={setAdding} onEdit={setEditing} onComments={setCommentsFor}
          live={{ block: liveBlock, open: setLiveBlock, editors: (k) => here.filter((u) => u.editing === k && u.user_id !== me?.id) }} />
      </Card>

      {adding && !adding.existing && (
        <ItemFormModal opened onClose={() => setAdding(null)} parent={adding.parent} position={adding.position}
          types={allowedTypes} defaultType={allowedTypes.find((t) => t !== "heading")} navigateOnCreate={false} />
      )}
      {adding?.existing && <InsertExisting target={adding} types={allowedTypes} onClose={() => setAdding(null)} />}
      {editing && editItem.data && <ItemFormModal opened onClose={() => setEditing(null)} item={editItem.data as ItemDetail} />}
      <CommentsDrawer docKey={docKey} itemKey={commentsFor} onClose={() => setCommentsFor(null)} />
      <HistoryDrawer docKey={docKey} opened={historyOpen} onClose={() => setHistoryOpen(false)} />
      <CompareDialog docKey={docKey} opened={compareOpen} onClose={() => setCompareOpen(false)} />
    </>
  );
}

function InsertExisting({ target, types, onClose }: { target: AddTarget; types: string[]; onClose: () => void }) {
  const { key } = useProjectCtx();
  const [itemKey, setItemKey] = useState<string | null>(null);
  const insert = useProjectMutation(key, () => api.post(`/projects/${key}/links`, {
    type: "contains", source: target.parent, target: itemKey, position: target.position,
  }), { success: "Item inserted (reused — it stays one item with one history)", onSuccess: onClose });
  return (
    <Modal opened onClose={onClose} title="Insert an existing item">
      <Stack>
        <Text size="sm" c="dimmed">The item is referenced, not copied: it appears in several documents but has one content, version history and workflow.</Text>
        <ItemPicker label="Item" types={types} value={itemKey} onChange={setItemKey} testId="insert-existing" />
        <Group justify="flex-end"><Button onClick={() => insert.mutate(undefined)} disabled={!itemKey} loading={insert.isPending} data-testid="insert-existing-go">Insert</Button></Group>
      </Stack>
    </Modal>
  );
}

function CommentsDrawer({ docKey, itemKey, onClose }: { docKey: string; itemKey: string | null; onClose: () => void }) {
  const { key, can } = useProjectCtx();
  const isDoc = itemKey === "__doc__";
  const threads = useThreads(key, isDoc ? docKey : itemKey, isDoc).data ?? [];
  return (
    <Drawer opened={!!itemKey} onClose={onClose} position="right" size="md"
      title={<Text fw={600}>{isDoc ? `All comments in ${docKey}` : `Comments on ${itemKey}`}</Text>}>
      {itemKey && (
        <CommentThreads projectKey={key} threads={threads} itemKey={isDoc ? docKey : itemKey} documentKey={docKey}
          canWrite={can("contributor")} canModerate={can("manager")} showItemKeys={isDoc} />
      )}
    </Drawer>
  );
}

interface LiveBlocks { block: string | null; open: (key: string | null) => void; editors: (key: string) => PresenceUser[] }

function PresenceBar({ people, meId }: { people: PresenceUser[]; meId?: string }) {
  const users = new Map<string, { id: string; name: string; color: string; editing: boolean }>();
  for (const u of people) {
    const prev = users.get(u.user_id);
    users.set(u.user_id, { id: u.user_id, name: u.user_id === meId ? `${u.name} (you)` : u.name, color: u.color, editing: (prev?.editing ?? false) || !!u.editing });
  }
  const list = Array.from(users.values());
  if (list.length === 0) return null;
  const editing = list.filter((u) => u.editing).length;
  return (
    <Tooltip label={`${list.length} ${list.length === 1 ? "person" : "people"} in this document${editing ? `, ${editing} editing` : ""}`}>
      <Group gap={6} className="presence-bar" data-testid="doc-presence">
        <ParticipantAvatars people={list} size={24} />
        <Text size="xs" c="dimmed">{list.length}</Text>
      </Group>
    </Tooltip>
  );
}

function Blocks({ nodes, depth, parentKey, editable, historical, onAdd, onEdit, onComments, live }: {
  nodes: DocNode[]; depth: number; parentKey: string; editable: boolean; historical: boolean;
  onAdd: (t: AddTarget) => void; onEdit: (key: string) => void; onComments: (key: string) => void; live: LiveBlocks;
}) {
  const { key } = useProjectCtx();
  const move = useProjectMutation(key, (v: { item: string; position: number }) =>
    api.post(`/projects/${key}/items/${v.item}/move`, { parent: parentKey, position: v.position }));
  const restore = useProjectMutation(key, (v: { item: string; version: number }) =>
    api.post(`/projects/${key}/items/${v.item}/restore`, { version_no: v.version }), { success: "Restored as a new version" });
  // Positions are floats: moving between two siblings takes the midpoint of their positions.
  const pos = nodes.map((x, j) => x.position ?? j + 1);
  return (
    <Stack gap={4}>
      {nodes.map((n, i) => (
        <DocBlock key={`${n.item_id}-${n.link_id}`} n={n} depth={depth} parentKey={parentKey} editable={editable}
          historical={historical} onAdd={onAdd} onEdit={onEdit} onComments={onComments} live={live}
          upTarget={i > 0 ? ((i > 1 ? pos[i - 2] : pos[i - 1] - 1) + pos[i - 1]) / 2 : null}
          downTarget={i < nodes.length - 1 ? (pos[i + 1] + (i < nodes.length - 2 ? pos[i + 2] : pos[i + 1] + 1)) / 2 : null}
          afterTarget={i < nodes.length - 1 ? (pos[i] + pos[i + 1]) / 2 : null}
          onMove={(position) => move.mutate({ item: n.key, position })}
          onRestore={() => restore.mutate({ item: n.key, version: n.version_no })} />
      ))}
    </Stack>
  );
}

/** One block. The action toolbar is only rendered while the pointer or focus is on the block (long documents). */
function DocBlock({ n, depth, parentKey, editable, historical, onAdd, onEdit, onComments, live, upTarget, downTarget,
  afterTarget, onMove, onRestore }: {
  n: DocNode; depth: number; parentKey: string; editable: boolean; historical: boolean; onAdd: (t: AddTarget) => void;
  onEdit: (key: string) => void; onComments: (key: string) => void; live: LiveBlocks; upTarget: number | null;
  downTarget: number | null; afterTarget: number | null; onMove: (position: number) => void; onRestore: () => void;
}) {
  const { key } = useProjectCtx();
  const [active, setActive] = useState(false);
  const editors = live.editors(n.key);
  const editingHere = live.block === n.key;
  return (
    <div className={depth ? "doc-indent" : undefined} style={{ marginLeft: depth ? 18 : 0 }}>
      <div className={`doc-block${editors.length ? " doc-block-live" : ""}${editingHere ? " doc-block-editing" : ""}`}
        data-testid={`block-${n.key}`} onDoubleClick={() => editable && !n.frozen && live.open(n.key)}
        onPointerEnter={() => setActive(true)} onPointerLeave={() => setActive(false)}
        onFocus={() => setActive(true)}>
        {editors.length > 0 && !editingHere && (
          <Group gap={6} mb={4} data-testid={`block-editors-${n.key}`}>
            <ParticipantAvatars size={18} people={editors.map((u) => ({ id: u.user_id, name: u.name, color: u.color, editing: true }))} />
            <Text size="xs" c="orange.7">{Array.from(new Set(editors.map((u) => u.name))).join(", ")} editing live</Text>
          </Group>
        )}
        {editingHere ? (
          <LiveEditor target={{ id: n.item_id, key: n.key, title: n.title, description: n.raw_description, content_hash: n.content_hash }}
            projectKey={key} canWrite={editable && !n.frozen} onClose={() => live.open(null)} withBody={!n.is_heading}
            testId={`live-${n.key}`} />
        ) : (
          <Group justify="space-between" wrap="nowrap" align="flex-start">
            <div style={{ minWidth: 0, flex: 1 }}>
              {n.is_heading ? (
                <Title order={Math.min(3 + depth, 6) as 3 | 4 | 5 | 6} mt={depth === 0 ? "sm" : 4}>{n.display_title}</Title>
              ) : (
                <>
                  <Group gap={6} mb={2}>
                    <Link to={`/p/${key}/items/${n.key}${historical ? `?version=${n.version_no}` : ""}`} className="item-key">{n.key}</Link>
                    <Text fw={600} size="sm">{n.title}</Text>
                    {n.state && <Badge size="xs" variant="light" color={stateColor(n.state_color, n.state_category)}>{n.state}</Badge>}
                    <Text size="xs" c="dimmed" className="mono">{n.version}</Text>
                    {n.applicability && <Badge size="xs" color="pink" variant="light" className="mono" style={{ textTransform: "none" }}>{n.applicability}</Badge>}
                    {n.suspect_links > 0 && <Badge size="xs" color="orange" variant="light" leftSection={<IconAlertTriangle size={10} />} title="Has suspect links — a linked item changed">suspect</Badge>}
                    {n.reused_in > 0 && <Badge size="xs" variant="outline" leftSection={<IconLink size={10} />} title={`Also used in ${n.reused_in} other place(s)`}>reused</Badge>}
                    {n.comment_count > 0 && (
                      <Badge size="xs" color="yellow" variant="light" className="clickable" leftSection={<IconMessage size={10} />}
                        onClick={() => onComments(n.key)} data-testid={`comments-${n.key}`}>{n.comment_count}</Badge>
                    )}
                  </Group>
                  <RichText html={n.description} empty="" />
                </>
              )}
            </div>
            {active && (
              <Group gap={2} className="doc-actions" wrap="nowrap">
                {historical ? (
                  <>
                    <Tooltip label="Open this version"><ActionIcon variant="subtle" size="sm" component={Link} to={`/p/${key}/items/${n.key}?version=${n.version_no}`}><IconEye size={14} /></ActionIcon></Tooltip>
                    {!n.is_heading && (
                      <Tooltip label="Restore this text in the live item (new version)">
                        <ActionIcon variant="subtle" size="sm" onClick={onRestore}><IconArrowBackUp size={14} /></ActionIcon>
                      </Tooltip>
                    )}
                  </>
                ) : (
                  <>
                    <Tooltip label="Comments"><ActionIcon variant="subtle" size="sm" onClick={() => onComments(n.key)} data-testid={`comment-on-${n.key}`}><IconMessage size={14} /></ActionIcon></Tooltip>
                    {editable && (
                      <>
                        <Tooltip label="Move up"><ActionIcon variant="subtle" size="sm" disabled={upTarget === null}
                          onClick={() => upTarget !== null && onMove(upTarget)}><IconArrowUp size={14} /></ActionIcon></Tooltip>
                        <Tooltip label="Move down"><ActionIcon variant="subtle" size="sm" disabled={downTarget === null}
                          onClick={() => downTarget !== null && onMove(downTarget)}><IconArrowDown size={14} /></ActionIcon></Tooltip>
                        {!n.frozen && <Tooltip label="Edit text live (double-click)"><ActionIcon variant="subtle" size="sm" onClick={() => live.open(n.key)} data-testid={`edit-${n.key}`}><IconEdit size={14} /></ActionIcon></Tooltip>}
                        <Menu position="bottom-end">
                          <Menu.Target><ActionIcon variant="subtle" size="sm" data-testid={`add-${n.key}`}><IconPlus size={14} /></ActionIcon></Menu.Target>
                          <Menu.Dropdown>
                            <Menu.Item onClick={() => onAdd({ parent: parentKey, position: afterTarget })}>Add after</Menu.Item>
                            {(n.is_heading || n.children.length > 0) && <Menu.Item onClick={() => onAdd({ parent: n.key, position: null })}>Add inside</Menu.Item>}
                            <Menu.Item onClick={() => onAdd({ parent: parentKey, position: afterTarget, existing: true })}>Insert existing item after</Menu.Item>
                            {!n.frozen && <Menu.Divider />}
                            {!n.frozen && <Menu.Item onClick={() => onEdit(n.key)} data-testid={`props-${n.key}`}>Properties (title, attributes)…</Menu.Item>}
                          </Menu.Dropdown>
                        </Menu>
                      </>
                    )}
                  </>
                )}
              </Group>
            )}
          </Group>
        )}
      </div>
      {n.children.length > 0 && (
        <Blocks nodes={n.children} depth={depth + 1} parentKey={n.key} editable={editable} historical={historical}
          onAdd={onAdd} onEdit={onEdit} onComments={onComments} live={live} />
      )}
    </div>
  );
}
