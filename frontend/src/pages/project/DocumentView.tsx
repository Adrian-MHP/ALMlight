import { useState } from "react";
import {
  ActionIcon, Anchor, Badge, Breadcrumbs, Button, Card, Center, Group, Loader, Menu, Stack, Text, Title, Tooltip,
} from "@mantine/core";
import { IconArrowDown, IconArrowUp, IconDownload, IconEdit, IconExternalLink, IconGitBranch, IconPlus } from "@tabler/icons-react";
import { Link, useParams } from "react-router-dom";
import { api, downloadUrl } from "@/api/client";
import { useItem, useProjectMutation, useTree } from "@/api/hooks";
import type { ItemDetail, TreeNode } from "@/api/types";
import { StateBadge, SuspectBadge } from "@/components/badges";
import { Markdown } from "@/components/Markdown";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";
import { BranchBar } from "./BranchMerge";

interface AddTarget { parent: string; position: number | null; }

/** Document view of a specification: a readable, ordered outline of individually managed items. */
export function DocumentView() {
  const { specKey = "" } = useParams();
  const { key, model, can } = useProjectCtx();
  const spec = useItem(key, specKey.toUpperCase());
  const tree = useTree(key, specKey.toUpperCase(), true);
  const [adding, setAdding] = useState<AddTarget | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [branching, setBranching] = useState(false);
  const editItem = useItem(key, editing ?? "", !!editing);

  if (spec.isLoading || tree.isLoading) return <Center mt={80}><Loader /></Center>;
  if (!spec.data || !tree.data) return <Text>Not found</Text>;
  const editableDoc = can("contributor") && !spec.data.lifecycle.frozen;
  const childTypes = model.config.link_types.filter((lt) => lt.structural)
    .flatMap((lt) => (lt.sources.includes(spec.data!.type_key) || lt.sources.includes("heading") ? lt.targets : []));
  const allowedTypes = Array.from(new Set(childTypes)).filter((t) => model.type(t) && !model.type(t)!.document);

  return (
    <>
      <Breadcrumbs mb="xs" separator="›">
        <Anchor component={Link} to={`/p/${key}/documents`} size="sm">Documents</Anchor>
        <Text size="sm" className="item-key">{spec.data.key}</Text>
      </Breadcrumbs>
      <Group justify="space-between" mb="md" align="flex-start">
        <Stack gap={4}>
          <Group gap="xs">
            <Title order={2} size="h3">{spec.data.title}</Title>
            <StateBadge item={spec.data} size="md" />
            <Badge variant="default" className="mono">{spec.data.version}</Badge>
          </Group>
          <Text size="xs" c="dimmed">Each block is an item with its own version, workflow and traceability. Release the document once all items are approved.</Text>
        </Stack>
        <Group gap="xs">
          <Button variant="default" component={Link} to={`/p/${key}/items/${spec.data.key}`} leftSection={<IconExternalLink size={16} />}>Document item</Button>
          <Button variant="default" component="a" href={downloadUrl(`/projects/${key}/items/${spec.data.key}/reqif`)} leftSection={<IconDownload size={16} />}>ReqIF</Button>
          {can("contributor") && <Button variant="default" leftSection={<IconGitBranch size={16} />} onClick={() => setBranching(true)} data-testid="create-branch">Branch</Button>}
          {editableDoc && <Button leftSection={<IconPlus size={16} />} onClick={() => setAdding({ parent: spec.data!.key, position: null })} data-testid="doc-add">Add</Button>}
        </Group>
      </Group>
      <BranchBar docKey={spec.data.key} creating={branching} onCloseCreate={() => setBranching(false)} />
      <Card withBorder padding="lg" data-testid="document">
        {tree.data.children.length === 0 && <Text c="dimmed">This document is empty. Add headings and requirements.</Text>}
        <Blocks nodes={tree.data.children} depth={0} parentKey={spec.data.key} editable={editableDoc}
          onAdd={setAdding} onEdit={setEditing} />
      </Card>
      {adding && (
        <ItemFormModal opened onClose={() => setAdding(null)} parent={adding.parent} position={adding.position}
          types={allowedTypes} defaultType={allowedTypes.find((t) => t !== "heading")} navigateOnCreate={false} />
      )}
      {editing && editItem.data && (
        <ItemFormModal opened onClose={() => setEditing(null)} item={editItem.data as ItemDetail} />
      )}
    </>
  );
}

function Blocks({ nodes, depth, parentKey, editable, onAdd, onEdit }: {
  nodes: TreeNode[]; depth: number; parentKey: string; editable: boolean;
  onAdd: (t: AddTarget) => void; onEdit: (key: string) => void;
}) {
  const { key } = useProjectCtx();
  const move = useProjectMutation(key, (v: { item: string; position: number }) =>
    api.post(`/projects/${key}/items/${v.item}/move`, { parent: parentKey, position: v.position }));
  return (
    <Stack gap={4}>
      {nodes.map((n, i) => {
        const isHeading = n.type_key === "heading";
        // Positions are floats: moving between two siblings takes the midpoint of their positions.
        const pos = nodes.map((x, j) => x.link?.position ?? j + 1);
        const upTarget = i > 0 ? ((i > 1 ? pos[i - 2] : pos[i - 1] - 1) + pos[i - 1]) / 2 : null;
        const downTarget = i < nodes.length - 1 ? (pos[i + 1] + (i < nodes.length - 2 ? pos[i + 2] : pos[i + 1] + 1)) / 2 : null;
        const afterTarget = i < nodes.length - 1 ? (pos[i] + pos[i + 1]) / 2 : null;
        return (
          <div key={n.id} style={{ marginLeft: depth * 18 }}>
            <div className="doc-block" data-testid={`block-${n.key}`}>
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                <div style={{ minWidth: 0, flex: 1 }}>
                  {isHeading ? (
                    <Title order={Math.min(3 + depth, 6) as 3 | 4 | 5 | 6} mt={depth === 0 ? "sm" : 4}>{n.title}</Title>
                  ) : (
                    <>
                      <Group gap={6} mb={2}>
                        <Link to={`/p/${key}/items/${n.key}`} className="item-key">{n.key}</Link>
                        <Text fw={600} size="sm">{n.title}</Text>
                        <StateBadge item={n} size="xs" />
                        <Text size="xs" c="dimmed" className="mono">{n.version}</Text>
                        {n.applicability && <Badge size="xs" color="pink" variant="light" className="mono" style={{ textTransform: "none" }}>{n.applicability}</Badge>}
                        {n.link?.suspect && <SuspectBadge />}
                      </Group>
                      <Markdown text={n.description} empty="" />
                    </>
                  )}
                </div>
                {editable && (
                  <Group gap={2} className="doc-actions" wrap="nowrap">
                    <Tooltip label="Move up"><ActionIcon variant="subtle" size="sm" disabled={upTarget === null}
                      onClick={() => upTarget !== null && move.mutate({ item: n.key, position: upTarget })}><IconArrowUp size={14} /></ActionIcon></Tooltip>
                    <Tooltip label="Move down"><ActionIcon variant="subtle" size="sm" disabled={downTarget === null}
                      onClick={() => downTarget !== null && move.mutate({ item: n.key, position: downTarget })}><IconArrowDown size={14} /></ActionIcon></Tooltip>
                    {!n.lifecycle.frozen && <Tooltip label="Edit"><ActionIcon variant="subtle" size="sm" onClick={() => onEdit(n.key)}><IconEdit size={14} /></ActionIcon></Tooltip>}
                    <Menu position="bottom-end">
                      <Menu.Target><ActionIcon variant="subtle" size="sm"><IconPlus size={14} /></ActionIcon></Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Item onClick={() => onAdd({ parent: parentKey, position: afterTarget })}>Add after</Menu.Item>
                        {(isHeading || n.children.length > 0) && <Menu.Item onClick={() => onAdd({ parent: n.key, position: null })}>Add inside</Menu.Item>}
                      </Menu.Dropdown>
                    </Menu>
                  </Group>
                )}
              </Group>
            </div>
            {n.children.length > 0 && <Blocks nodes={n.children} depth={depth + 1} parentKey={n.key} editable={editable} onAdd={onAdd} onEdit={onEdit} />}
          </div>
        );
      })}
    </Stack>
  );
}
