import { useState } from "react";
import { Badge, Button, Drawer, Group, Modal, ScrollArea, Stack, Text, TextInput, Timeline, Title } from "@mantine/core";
import { IconBinaryTree, IconGitCompare, IconHistory } from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useDocumentHistory, useProjectMutation } from "@/api/hooks";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";

const ACTION_LABEL: Record<string, string> = {
  "item.created": "created", "item.updated": "edited", "item.revised": "revised", "item.transitioned": "state",
  "link.created": "structure", "link.deleted": "structure", "link.updated": "moved", "comment.added": "comment",
  "baseline.created": "baseline", "item.deleted": "deleted", "item.restored": "restored", "approval.requested": "approval",
  "approval.cancelled": "approval", "comment.resolved": "comment", "comment.reopened": "comment", "comment.deleted": "comment",
  "link.confirmed": "suspect cleared", "item.owner_changed": "owner", "item.attachment_added": "attachment",
  "item.attachment_removed": "attachment", "collection.document_set": "collection", "collection.document_removed": "collection",
  "branch.created": "branch", "branch.merged": "merge",
};

/** Timeline of the document: every change point can be opened (time travel) or compared with the live state. */
export function HistoryDrawer({ docKey, opened, onClose }: { docKey: string; opened: boolean; onClose: () => void }) {
  const { key } = useProjectCtx();
  const navigate = useNavigate();
  const { data } = useDocumentHistory(key, docKey, opened);
  const go = (params: string) => { onClose(); navigate(`/p/${key}/documents/${docKey}${params}`); };
  return (
    <Drawer opened={opened} onClose={onClose} position="right" size="lg" title={<Group gap={6}><IconHistory size={18} /><Text fw={600}>History of {docKey}</Text></Group>}>
      <ScrollArea h="calc(100vh - 90px)" offsetScrollbars>
        <Stack gap="md" data-testid="history-drawer">
          {data && data.baselines.length > 0 && (
            <div>
              <Title order={6} mb={6}>Baselines</Title>
              <Stack gap={6}>
                {data.baselines.map((b) => (
                  <Group key={b.id} justify="space-between" wrap="nowrap">
                    <div>
                      <Group gap={6}><IconBinaryTree size={14} /><Text size="sm" fw={500}>{b.name}</Text>
                        {b.scope_is_document ? <Badge size="xs" variant="light">document</Badge> : <Badge size="xs" variant="outline">project</Badge>}</Group>
                      <Text size="xs" c="dimmed">{fmtDateTime(b.created_at)} · {b.revision_rule}</Text>
                    </div>
                    <Group gap={4} wrap="nowrap">
                      <Button size="compact-xs" variant="light" onClick={() => go(`?baseline=${b.id}`)} data-testid={`open-baseline-${b.name}`}>Open</Button>
                      <Button size="compact-xs" variant="subtle" onClick={() => go(`/compare?l_bl=${b.id}`)}>Compare</Button>
                    </Group>
                  </Group>
                ))}
              </Stack>
            </div>
          )}
          <div>
            <Title order={6} mb={6}>Changes</Title>
            <Timeline bulletSize={12} lineWidth={2}>
              {(data?.entries ?? []).map((e) => (
                <Timeline.Item key={e.id} title={<Text size="sm" lineClamp={2} style={{ overflowWrap: "anywhere" }}>{e.summary}</Text>}>
                  <Group gap={6} wrap="wrap">
                    <Text size="xs" c="dimmed">{e.actor} · {fmtDateTime(e.ts)} · {ACTION_LABEL[e.action] ?? e.action}</Text>
                    <Button size="compact-xs" variant="subtle" onClick={() => go(`?at=${encodeURIComponent(e.ts)}`)} data-testid="history-open">Open</Button>
                    <Button size="compact-xs" variant="subtle" leftSection={<IconGitCompare size={12} />}
                      onClick={() => go(`/compare?l_at=${encodeURIComponent(e.ts)}`)}>Compare with live</Button>
                  </Group>
                </Timeline.Item>
              ))}
            </Timeline>
          </div>
        </Stack>
      </ScrollArea>
    </Drawer>
  );
}

export function DocBaselineButton({ docKey }: { docKey: string }) {
  const { key, can } = useProjectCtx();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const create = useProjectMutation(key, () => api.post(`/projects/${key}/baselines`, { name, scope: docKey, description: `Document baseline of ${docKey}` }),
    { success: "Document baseline created", onSuccess: () => { setOpen(false); setName(""); } });
  if (!can("reviewer")) return null;
  return (
    <>
      <Button variant="default" leftSection={<IconBinaryTree size={16} />} onClick={() => setOpen(true)} data-testid="doc-baseline">Baseline</Button>
      <Modal opened={open} onClose={() => setOpen(false)} title={`Baseline ${docKey}`}>
        <Stack>
          <Text size="sm" c="dimmed">Freezes this document with all its items and their current versions. You can open, compare and export it at any time.</Text>
          <TextInput label="Name" placeholder="e.g. Design review 2" value={name} onChange={(e) => setName(e.currentTarget.value)} data-testid="doc-baseline-name" />
          <Group justify="flex-end"><Button onClick={() => create.mutate(undefined)} disabled={!name.trim()} loading={create.isPending} data-testid="doc-baseline-create">Create</Button></Group>
        </Stack>
      </Modal>
    </>
  );
}
