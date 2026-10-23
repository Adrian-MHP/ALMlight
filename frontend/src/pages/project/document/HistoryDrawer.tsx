import { useState } from "react";
import { Badge, Button, Drawer, Group, Modal, ScrollArea, Stack, Text, TextInput, Timeline, Title } from "@mantine/core";
import { IconBinaryTree, IconGitCompare, IconHistory } from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useDocumentHistory, useProjectMutation } from "@/api/hooks";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { tx } from "@/lib/i18n";

const ACTION_LABEL: Record<string, string> = {
  "item.created": tx("created"), "item.updated": tx("edited"), "item.revised": tx("revised"), "item.transitioned": tx("state"),
  "link.created": tx("structure"), "link.deleted": tx("structure"), "link.updated": tx("moved"), "comment.added": tx("comment"),
  "baseline.created": tx("baseline"), "item.deleted": tx("deleted"), "item.restored": tx("restored"), "approval.requested": tx("approval"),
  "approval.cancelled": tx("approval"), "comment.resolved": tx("comment"), "comment.reopened": tx("comment"), "comment.deleted": tx("comment"),
  "link.confirmed": tx("suspect cleared"), "item.owner_changed": tx("owner"), "item.attachment_added": tx("attachment"),
  "item.attachment_removed": tx("attachment"), "collection.document_set": tx("collection"), "collection.document_removed": tx("collection"),
  "branch.created": tx("branch"), "branch.merged": tx("merge"),
};

/** Timeline of the document: every change point can be opened (time travel) or compared with the live state. */
export function HistoryDrawer({ docKey, opened, onClose }: { docKey: string; opened: boolean; onClose: () => void }) {
  const { key } = useProjectCtx();
  const navigate = useNavigate();
  const { data } = useDocumentHistory(key, docKey, opened);
  const go = (params: string) => { onClose(); navigate(`/p/${key}/documents/${docKey}${params}`); };
  return (
    <Drawer opened={opened} onClose={onClose} position="right" size="lg" title={<Group gap={6}><IconHistory size={18} /><Text fw={600}>{tx("History of {docKey}", { docKey: docKey })}</Text></Group>}>
      <ScrollArea h="calc(100vh - 90px)" offsetScrollbars>
        <Stack gap="md" data-testid="history-drawer">
          {data && data.baselines.length > 0 && (
            <div>
              <Title order={6} mb={6}>{tx("Baselines")}</Title>
              <Stack gap={6}>
                {data.baselines.map((b) => (
                  <Group key={b.id} justify="space-between" wrap="nowrap">
                    <div>
                      <Group gap={6}><IconBinaryTree size={14} /><Text size="sm" fw={500}>{b.name}</Text>
                        {b.scope_is_document ? <Badge size="xs" variant="light">{tx("document")}</Badge> : <Badge size="xs" variant="outline">{tx("project")}</Badge>}</Group>
                      <Text size="xs" c="dimmed">{fmtDateTime(b.created_at)} · {b.revision_rule}</Text>
                    </div>
                    <Group gap={4} wrap="nowrap">
                      <Button size="compact-xs" variant="light" onClick={() => go(`?baseline=${b.id}`)} data-testid={`open-baseline-${b.name}`}>{tx("Open")}</Button>
                      <Button size="compact-xs" variant="subtle" onClick={() => go(`/compare?l_bl=${b.id}`)}>{tx("Compare")}</Button>
                    </Group>
                  </Group>
                ))}
              </Stack>
            </div>
          )}
          <div>
            <Title order={6} mb={6}>{tx("Changes")}</Title>
            <Timeline bulletSize={12} lineWidth={2}>
              {(data?.entries ?? []).map((e) => (
                <Timeline.Item key={e.id} title={<Text size="sm" lineClamp={2} style={{ overflowWrap: "anywhere" }}>{e.summary}</Text>}>
                  <Group gap={6} wrap="wrap">
                    <Text size="xs" c="dimmed">{e.actor} · {fmtDateTime(e.ts)} · {ACTION_LABEL[e.action] ?? e.action}</Text>
                    <Button size="compact-xs" variant="subtle" onClick={() => go(`?at=${encodeURIComponent(e.ts)}`)} data-testid="history-open">{tx("Open")}</Button>
                    <Button size="compact-xs" variant="subtle" leftSection={<IconGitCompare size={12} />}
                      onClick={() => go(`/compare?l_at=${encodeURIComponent(e.ts)}`)}>{tx("Compare with live")}</Button>
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
  const create = useProjectMutation(key, () => api.post(`/projects/${key}/baselines`, { name, scope: docKey, description: tx("Document baseline of {docKey}", { docKey: docKey }) }),
    { success: tx("Document baseline created"), onSuccess: () => { setOpen(false); setName(""); } });
  if (!can("reviewer")) return null;
  return (
    <>
      <Button variant="default" leftSection={<IconBinaryTree size={16} />} onClick={() => setOpen(true)} data-testid="doc-baseline">{tx("Baseline")}</Button>
      <Modal opened={open} onClose={() => setOpen(false)} title={tx("Baseline {docKey}", { docKey: docKey })}>
        <Stack>
          <Text size="sm" c="dimmed">{tx("Freezes this document with all its items and their current versions. You can open, compare and export it at any time.")}</Text>
          <TextInput label={tx("Name")} placeholder={tx("e.g. Design review 2")} value={name} onChange={(e) => setName(e.currentTarget.value)} data-testid="doc-baseline-name" />
          <Group justify="flex-end"><Button onClick={() => create.mutate(undefined)} disabled={!name.trim()} loading={create.isPending} data-testid="doc-baseline-create">{tx("Create")}</Button></Group>
        </Stack>
      </Modal>
    </>
  );
}
