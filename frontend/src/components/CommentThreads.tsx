import { useState } from "react";
import { ActionIcon, Avatar, Badge, Button, Card, Group, Stack, Switch, Text, Tooltip } from "@mantine/core";
import { IconArrowBackUp, IconCheck, IconMessageReply, IconTrash } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { useMe, useProjectMutation } from "@/api/hooks";
import type { CommentThread } from "@/api/types";
import { fmtDateTime } from "@/lib/format";
import { Markdown } from "./Markdown";
import { emphasizeMentions, MentionTextarea } from "./MentionTextarea";

interface Props {
  projectKey: string;
  threads: CommentThread[];
  /** Item that new comments are added to (omit to hide the "new comment" box). */
  itemKey?: string | null;
  /** Document context of new comments. */
  documentKey?: string | null;
  canWrite: boolean;
  canModerate: boolean;
  showItemKeys?: boolean;
}

/** Threaded comments with replies and resolve/reopen — shared by the item page and the document view. */
export function CommentThreads({ projectKey, threads, itemKey, documentKey, canWrite, canModerate, showItemKeys }: Props) {
  const me = useMe().data!;
  const [showResolved, setShowResolved] = useState(false);
  const [body, setBody] = useState("");
  const add = useProjectMutation(projectKey, (v: { item: string; body: string; parent_id?: string }) =>
    api.post(`/projects/${projectKey}/items/${v.item}/comments`, { body: v.body, parent_id: v.parent_id ?? null, document: documentKey ?? null }),
  { onSuccess: () => setBody("") });
  const resolve = useProjectMutation(projectKey, (v: { item: string; id: string; resolved: boolean }) =>
    api.post(`/projects/${projectKey}/items/${v.item}/comments/${v.id}/resolve?resolved=${v.resolved}`));
  const del = useProjectMutation(projectKey, (v: { item: string; id: string }) => api.del(`/projects/${projectKey}/items/${v.item}/comments/${v.id}`));
  const visible = threads.filter((t) => showResolved || !t.resolved);
  const resolvedCount = threads.filter((t) => t.resolved).length;

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text size="sm" c="dimmed">{threads.length - resolvedCount} open thread(s){resolvedCount ? `, ${resolvedCount} resolved` : ""}</Text>
        {resolvedCount > 0 && <Switch size="xs" label="Show resolved" checked={showResolved} onChange={(e) => setShowResolved(e.currentTarget.checked)} />}
      </Group>
      {visible.map((t) => (
        <Card key={t.id} withBorder padding="sm" style={{ opacity: t.resolved ? 0.7 : 1 }} data-testid={`thread-${t.id}`}>
          <CommentBody c={t} projectKey={projectKey} showItemKey={showItemKeys} />
          {t.replies.length > 0 && (
            <Stack gap={6} mt="xs" pl="md" style={{ borderLeft: "2px solid var(--mantine-color-default-border)" }}>
              {t.replies.map((r) => <CommentBody key={r.id} c={r} projectKey={projectKey} />)}
            </Stack>
          )}
          <Group justify="space-between" mt="xs">
            <Group gap={6}>
              {t.resolved && <Badge size="xs" color="green" variant="light">resolved by {t.resolved_by?.display_name}</Badge>}
            </Group>
            <Group gap={4}>
              {canWrite && t.item_key && (
                t.resolved
                  ? <Tooltip label="Reopen"><ActionIcon variant="subtle" size="sm" onClick={() => resolve.mutate({ item: t.item_key!, id: t.id, resolved: false })}><IconArrowBackUp size={14} /></ActionIcon></Tooltip>
                  : <Tooltip label="Resolve"><ActionIcon variant="subtle" size="sm" color="green" onClick={() => resolve.mutate({ item: t.item_key!, id: t.id, resolved: true })} data-testid="resolve-thread"><IconCheck size={14} /></ActionIcon></Tooltip>
              )}
              {(t.author?.id === me.id || canModerate) && t.item_key && (
                <Tooltip label="Delete thread"><ActionIcon variant="subtle" size="sm" color="red" onClick={() => del.mutate({ item: t.item_key!, id: t.id })}><IconTrash size={14} /></ActionIcon></Tooltip>
              )}
            </Group>
          </Group>
          {canWrite && t.item_key && <ReplyBox onSend={(text) => add.mutate({ item: t.item_key!, body: text, parent_id: t.id })} />}
        </Card>
      ))}
      {visible.length === 0 && <Text size="sm" c="dimmed">No comments.</Text>}
      {canWrite && itemKey && (
        <Card withBorder padding="sm">
          <MentionTextarea placeholder="Write a comment — @name notifies a colleague" autosize minRows={2} value={body} onChange={setBody} data-testid="comment-body" />
          <Group justify="flex-end" mt="xs">
            <Button size="xs" onClick={() => add.mutate({ item: itemKey, body })} disabled={!body.trim()} loading={add.isPending} data-testid="comment-add">Comment</Button>
          </Group>
        </Card>
      )}
    </Stack>
  );
}

function CommentBody({ c, projectKey, showItemKey }: { c: CommentThread; projectKey: string; showItemKey?: boolean }) {
  const name = c.external_author ?? c.author?.display_name ?? "?";
  return (
    <div>
      <Group gap="xs" mb={2}>
        <Avatar size={22} radius="xl" color={c.external_author ? "orange" : "indigo"}>{name.slice(0, 2).toUpperCase()}</Avatar>
        <Text size="sm" fw={600}>{name}</Text>
        {c.source === "word" && <Badge size="xs" variant="light" color="orange">from Word</Badge>}
        {showItemKey && c.item_key && <Link to={`/p/${projectKey}/items/${c.item_key}?tab=comments`} className="item-key">{c.item_key}</Link>}
        <Text size="xs" c="dimmed">{fmtDateTime(c.created_at)}</Text>
      </Group>
      <Markdown text={emphasizeMentions(c.body)} />
    </div>
  );
}

function ReplyBox({ onSend }: { onSend: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  if (!open) return <Button size="compact-xs" variant="subtle" mt={4} leftSection={<IconMessageReply size={12} />} onClick={() => setOpen(true)} data-testid="reply">Reply</Button>;
  return (
    <Group mt="xs" align="flex-end" wrap="nowrap">
      <div style={{ flex: 1 }}><MentionTextarea autosize minRows={1} value={text} onChange={setText} placeholder="Reply… (@name to notify)" data-testid="reply-body" /></div>
      <Button size="xs" disabled={!text.trim()} onClick={() => { onSend(text); setText(""); setOpen(false); }} data-testid="reply-send">Send</Button>
    </Group>
  );
}
