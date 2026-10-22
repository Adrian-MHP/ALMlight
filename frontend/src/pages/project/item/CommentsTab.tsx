import { useState } from "react";
import { ActionIcon, Avatar, Button, Card, Group, Stack, Text, Textarea } from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { api } from "@/api/client";
import { useComments, useMe, useProjectMutation } from "@/api/hooks";
import type { ItemDetail } from "@/api/types";
import { Markdown } from "@/components/Markdown";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";

export function CommentsTab({ item }: { item: ItemDetail }) {
  const { key, can } = useProjectCtx();
  const me = useMe().data!;
  const comments = useComments(key, item.key).data ?? [];
  const [body, setBody] = useState("");
  const add = useProjectMutation(key, () => api.post(`/projects/${key}/items/${item.key}/comments`, { body }), { onSuccess: () => setBody("") });
  const del = useProjectMutation(key, (id: string) => api.del(`/projects/${key}/items/${item.key}/comments/${id}`));
  return (
    <Stack>
      {comments.map((c) => (
        <Card key={c.id} withBorder padding="sm">
          <Group justify="space-between" mb={4}>
            <Group gap="xs">
              <Avatar size={24} radius="xl" color="indigo">{c.author?.display_name.slice(0, 2).toUpperCase()}</Avatar>
              <Text size="sm" fw={600}>{c.author?.display_name}</Text>
              <Text size="xs" c="dimmed">{fmtDateTime(c.created_at)}</Text>
            </Group>
            {(c.author?.id === me.id || can("manager")) && (
              <ActionIcon variant="subtle" color="red" onClick={() => del.mutate(c.id)}><IconTrash size={14} /></ActionIcon>
            )}
          </Group>
          <Markdown text={c.body} />
        </Card>
      ))}
      {comments.length === 0 && <Text c="dimmed">No comments yet.</Text>}
      {can("contributor") && (
        <Card withBorder padding="sm">
          <Textarea placeholder="Write a comment (Markdown)…" autosize minRows={2} value={body} onChange={(e) => setBody(e.currentTarget.value)} data-testid="comment-body" />
          <Group justify="flex-end" mt="xs">
            <Button size="xs" onClick={() => add.mutate(undefined)} disabled={!body.trim()} loading={add.isPending} data-testid="comment-add">Comment</Button>
          </Group>
        </Card>
      )}
    </Stack>
  );
}
