import { useEffect, useMemo, useState } from "react";
import { Alert, Avatar, Badge, Button, Group, Loader, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCheck, IconDeviceFloppy, IconLock, IconUsers, IconWifiOff } from "@tabler/icons-react";
import { EditorContent, useEditor } from "@tiptap/react";
import Collaboration from "@tiptap/extension-collaboration";
import CollaborationCaret from "@tiptap/extension-collaboration-caret";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { pk, useMe } from "@/api/hooks";
import { bodyExtensions, titleExtensions } from "@/components/rich/extensions";
import { itemSuggestion } from "@/components/rich/suggestion";
import { EditorFrame, uploadError, uploadImage } from "@/components/rich/EditorFrame";
import { useLiveSession, type LiveSession, type LiveTarget, type Participant } from "./session";
import { tx } from "@/lib/i18n";

const PALETTE = ["#e8590c", "#1971c2", "#2f9e44", "#c2255c", "#6741d9", "#0c8599", "#e67700", "#5c940d"];

/** Same colour per user as the server assigns (uuid as integer modulo the palette). */
export function userColor(id: string): string {
  try {
    return PALETTE[Number(BigInt(`0x${id.replace(/-/g, "")}`) % BigInt(PALETTE.length))];
  } catch {
    return PALETTE[0];
  }
}

export function ParticipantAvatars({ people, max = 5, size = 26 }: { people: { id: string; name: string; color: string; editing?: boolean }[]; max?: number; size?: number }) {
  if (!people.length) return null;
  return (
    <Tooltip.Group openDelay={200}>
      <Avatar.Group spacing={6}>
        {people.slice(0, max).map((p) => (
          <Tooltip key={p.id} label={`${p.name}${p.editing ? tx(" — editing") : ""}`}>
            <Avatar size={size} radius="xl" color={p.color} variant="filled" className={p.editing ? "avatar-editing" : undefined}
              style={{ background: p.color, outline: p.editing ? `2px solid ${p.color}` : undefined, outlineOffset: 2 }}
              data-testid={`avatar-${p.name}`}>
              {p.name.slice(0, 2).toUpperCase()}
            </Avatar>
          </Tooltip>
        ))}
        {people.length > max && <Avatar size={size} radius="xl">+{people.length - max}</Avatar>}
      </Avatar.Group>
    </Tooltip.Group>
  );
}

/**
 * Live editor for an item's title and text: everybody editing the same item sees each other's changes and cursors
 * instantly. "Save version" creates a new item version now; otherwise the session is saved when the last editor
 * leaves.
 */
export function LiveEditor({ target, projectKey, canWrite, onClose, withTitle = true, withBody = true, testId = "live-editor" }: {
  target: LiveTarget; projectKey: string; canWrite: boolean; onClose?: () => void; withTitle?: boolean; withBody?: boolean;
  testId?: string;
}) {
  const me = useMe().data;
  const qc = useQueryClient();
  const session = useLiveSession(target, me ? { id: me.id, name: me.display_name } : null,
    () => qc.invalidateQueries({ queryKey: pk(projectKey) }));
  if (!session || !me) return <Group p="md"><Loader size="sm" /><Text size="sm">{tx("Connecting…")}</Text></Group>;
  return <LiveEditorInner key={session.doc.guid} session={session} target={target} projectKey={projectKey}
    canWrite={canWrite} onClose={onClose} withTitle={withTitle} withBody={withBody} testId={testId}
    me={{ id: me.id, name: me.display_name }} />;
}

function LiveEditorInner({ session, target, projectKey, canWrite, onClose, withTitle, withBody, testId, me }: {
  session: LiveSession; target: LiveTarget; projectKey: string; canWrite: boolean; onClose?: () => void;
  withTitle: boolean; withBody: boolean; testId: string; me: { id: string; name: string };
}) {
  const qc = useQueryClient();
  const upload = useMemo(() => uploadImage(projectKey), [projectKey]);
  const suggestion = useMemo(() => itemSuggestion(projectKey), [projectKey]);
  const editable = canWrite && session.ready && session.status === "connected";
  const [saving, setSaving] = useState(false);
  const color = userColor(me.id);

  const body = useEditor({
    extensions: [
      ...bodyExtensions({ collaborative: true, onImageUpload: upload, onImageUploadError: uploadError, suggestion }),
      Collaboration.configure({ document: session.doc, field: "body" }),
      CollaborationCaret.configure({ provider: session.provider, user: { id: me.id, name: me.name, color } }),
    ],
    editable: false,
  }, [session.doc]);
  const title = useEditor({
    extensions: [...titleExtensions(tx("Title")), Collaboration.configure({ document: session.doc, field: "title" })],
    editable: false,
  }, [session.doc]);

  useEffect(() => {
    body?.setEditable(editable);
    title?.setEditable(editable);
  }, [body, title, editable]);

  async function save(close: boolean) {
    setSaving(true);
    try {
      const res = await api.post<{ saved: boolean; version?: string; error?: string }>(
        `/projects/${projectKey}/items/${target.key}/collab/save`);
      if (res.error) {
        notifications.show({ color: "red", title: tx("Not saved"), message: res.error });
        return;
      }
      if (res.saved) notifications.show({ color: "green", message: tx("Saved {key} as version {version}", { key: target.key, version: res.version }) });
      else if (!close) notifications.show({ message: tx("No changes to save") });
      qc.invalidateQueries({ queryKey: pk(projectKey) });
      if (close) onClose?.();
    } finally {
      setSaving(false);
    }
  }

  const others: Participant[] = session.participants.filter((p) => p.id !== me.id);
  const status = session.status === "connected"
    ? <Badge color="green" variant="dot" data-testid="live-status">{tx("Live{v}", { v: others.length ? tx(" · {v} editing", { v: others.length + 1 }) : "" })}</Badge>
    : session.status === "error"
      ? <Badge color="red" variant="light" leftSection={<IconWifiOff size={12} />}>{tx("Not connected")}</Badge>
      : <Badge color="yellow" variant="light" leftSection={<IconWifiOff size={12} />} data-testid="live-status">{tx("Connecting…")}</Badge>;

  return (
    <div className="live-editor" data-testid={testId}>
      <Group justify="space-between" mb={6} wrap="wrap" gap="xs">
        <Group gap="xs">
          {status}
          {!canWrite && <Badge color="gray" variant="light" leftSection={<IconLock size={12} />}>{tx("Read-only")}</Badge>}
          <ParticipantAvatars people={session.participants.map((p) => ({ ...p, editing: true }))} />
          {others.length > 0 && (
            <Text size="xs" c="dimmed"><IconUsers size={12} style={{ verticalAlign: -2 }} /> {others.length === 1 ? tx("{names} is editing too", { names: others[0].name }) : tx("{names} are editing too", { names: others.map((o) => o.name).join(", ") })}</Text>
          )}
        </Group>
        <Group gap="xs">
          {canWrite && (
            <Button size="xs" variant="default" leftSection={<IconDeviceFloppy size={14} />} loading={saving}
              onClick={() => save(false)} disabled={!session.ready} data-testid="live-save">{tx("Save version")}</Button>
          )}
          {onClose && (
            <Button size="xs" leftSection={<IconCheck size={14} />} onClick={() => (canWrite ? save(true) : onClose())}
              loading={saving} data-testid="live-done">{tx("Done")}</Button>
          )}
        </Group>
      </Group>
      {session.closed && (
        <Alert color="red" mb="xs" title={tx("Live editing unavailable")}>{session.closed.reason || tx("Connection closed ({code})", { code: session.closed.code })}</Alert>
      )}
      {withTitle && (
        <div className="live-title" data-testid={`${testId}-title`}>
          <EditorContent editor={title} />
        </div>
      )}
      {withBody && <EditorFrame editor={body} onImageUpload={canWrite ? upload : undefined} testId={`${testId}-body`} toolbar={canWrite} />}
      <Text size="xs" c="dimmed" mt={4}>
        {tx("Changes are shared instantly with everyone working on this item. A new version is saved with “Save version”, “Done” or automatically when the last editor leaves.")}{withBody ? <> {tx("Type")} <b>#</b> {tx("to reference an item.")}</> : null}
      </Text>
    </div>
  );
}
