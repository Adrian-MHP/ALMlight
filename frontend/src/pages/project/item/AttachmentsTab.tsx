import { useRef, useState } from "react";
import { ActionIcon, Anchor, Badge, Button, Card, FileButton, Group, Image, Menu, Modal, Stack, Table, Text, TextInput, Tooltip } from "@mantine/core";
import {
  IconDots, IconDownload, IconEye, IconFile, IconFileTypePdf, IconHistory, IconLock, IconLockOpen, IconPhoto, IconTrash,
  IconUpload,
} from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { api, downloadUrl } from "@/api/client";
import { useDirectory, useFileHistory, useMe, useProjectMutation } from "@/api/hooks";
import type { Attachment, ItemDetail } from "@/api/types";
import { fmtBytes, fmtDateTime, fmtRelative } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { tm, tx } from "@/lib/i18n";

const IMAGE = /^image\/(png|jpeg|gif|webp)$/;
const previewable = (a: Attachment) => IMAGE.test(a.content_type) || a.content_type === "application/pdf";

function FileIcon({ a }: { a: Attachment }) {
  if (a.content_type === "application/pdf") return <IconFileTypePdf size={18} color="var(--mantine-color-red-6)" />;
  if (a.content_type.startsWith("image/")) return <IconPhoto size={18} color="var(--mantine-color-blue-6)" />;
  return <IconFile size={18} color="var(--mantine-color-dimmed)" />;
}

/** Files of an item: versioned with it; check out for exclusive editing, check in new revisions, history, preview. */
export function AttachmentsTab({ item }: { item: ItemDetail }) {
  const { key, can } = useProjectCtx();
  const qc = useQueryClient();
  const upload = useProjectMutation(key, (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.upload(`/projects/${key}/items/${item.key}/attachments`, form);
  }, { success: tx("File attached (new iteration)") });
  const editable = can("contributor") && !item.lifecycle.frozen;
  const [history, setHistory] = useState<Attachment | null>(null);
  const [preview, setPreview] = useState<Attachment | null>(null);
  const checkedOut = item.attachments.filter((a) => a.checked_out_by).length;
  return (
    <>
      <Group mb="md" justify="space-between">
        <Group>
          {editable && (
            <FileButton onChange={(f) => f && upload.mutate(f)}>
              {(props) => <Button {...props} leftSection={<IconUpload size={16} />} loading={upload.isPending} data-testid="upload">{tx("Attach file")}</Button>}
            </FileButton>
          )}
          <Text size="xs" c="dimmed">{tx("Files are versioned with the item. Check a file out to edit it exclusively; checking in creates a new file revision.")}</Text>
        </Group>
        {checkedOut > 0 && <Badge color="orange" variant="light" leftSection={<IconLock size={12} />}>{tx("{checkedOut} checked out — blocks review and release", { checkedOut: checkedOut })}</Badge>}
      </Group>
      {item.lifecycle.frozen && item.attachments.length > 0 && (
        <Text size="xs" c="dimmed" mb="xs">{tx("The item is {label}: files can be downloaded, not changed. Create a new revision to change them.", { label: tm(item.lifecycle.label)?.toLowerCase() })}</Text>
      )}
      {item.attachments.length === 0 ? <Text c="dimmed">{tx("No files attached.")}</Text> : (
        <Card withBorder padding={0}>
          <Table.ScrollContainer minWidth={760}>
            <Table data-testid="files-table" verticalSpacing={6}>
              <Table.Thead><Table.Tr><Table.Th>{tx("File")}</Table.Th><Table.Th w={60}>{tx("Rev")}</Table.Th><Table.Th w={90}>{tx("Size")}</Table.Th><Table.Th w={210}>{tx("Modified")}</Table.Th><Table.Th w={230}>{tx("Status")}</Table.Th><Table.Th w={50} /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {item.attachments.map((a) => (
                  <FileRow key={a.id} a={a} item={item} editable={editable} onHistory={() => setHistory(a)} onPreview={() => setPreview(a)}
                    onChanged={() => qc.invalidateQueries({ queryKey: ["checkouts"] })} />
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Card>
      )}
      <HistoryModal item={item} file={history} onClose={() => setHistory(null)} />
      <Modal opened={!!preview} onClose={() => setPreview(null)} size="xl" title={preview?.filename}>
        {preview && <Image src={downloadUrl(`/projects/${key}/items/${item.key}/attachments/${preview.id}?inline=true`)} alt={preview.filename} fit="contain" mah="70vh" data-testid="file-preview" />}
      </Modal>
    </>
  );
}

function FileRow({ a, item, editable, onHistory, onPreview, onChanged }: {
  a: Attachment; item: ItemDetail; editable: boolean; onHistory: () => void; onPreview: () => void; onChanged: () => void;
}) {
  const { key, can } = useProjectCtx();
  const me = useMe().data;
  const users = useDirectory().data ?? [];
  const input = useRef<HTMLInputElement>(null);
  const [checkin, setCheckin] = useState<File | null>(null);
  const [comment, setComment] = useState("");
  const base = `/projects/${key}/items/${item.key}/attachments/${a.id}`;
  const mine = !!a.checked_out_by && a.checked_out_by.id === me?.id;
  const lockedByOther = !!a.checked_out_by && !mine;
  const checkout = useProjectMutation(key, () => api.post(`${base}/checkout`, {}), { success: tx("{filename} checked out", { filename: a.filename }), onSuccess: onChanged });
  const cancel = useProjectMutation(key, () => api.del(`${base}/checkout`), { success: tx("Check-out cancelled"), onSuccess: onChanged });
  const remove = useProjectMutation(key, () => api.del(base), { success: tx("File removed"), onSuccess: onChanged });
  const submit = useProjectMutation(key, () => {
    const form = new FormData();
    form.append("file", checkin!);
    if (comment.trim()) form.append("comment", comment.trim());
    return api.upload(`${base}/revisions`, form);
  }, { success: tx("Checked in {filename}", { filename: a.filename }), onSuccess: () => { setCheckin(null); setComment(""); onChanged(); } });
  const uploader = users.find((u) => u.id === a.uploaded_by)?.display_name;
  const pdf = a.content_type === "application/pdf";
  const inlineUrl = downloadUrl(`${base}?inline=true`);
  return (
    <Table.Tr data-testid={`file-${a.filename}`}>
      <Table.Td>
        <Group gap={8} wrap="nowrap">
          <FileIcon a={a} />
          <div style={{ minWidth: 0 }}>
            <Anchor href={downloadUrl(base)} size="sm">{a.filename}</Anchor>
            {a.comment && <Text size="xs" c="dimmed" lineClamp={1}>{a.comment}</Text>}
          </div>
          {previewable(a) && (
            <Tooltip label={pdf ? tx("Open in a new tab") : tx("Preview")}>
              {pdf ? <ActionIcon size="sm" variant="subtle" component="a" href={inlineUrl} target="_blank" rel="noopener" aria-label={tx("Preview")}><IconEye size={15} /></ActionIcon>
                : <ActionIcon size="sm" variant="subtle" onClick={onPreview} aria-label={tx("Preview")} data-testid="file-preview-open"><IconEye size={15} /></ActionIcon>}
            </Tooltip>
          )}
        </Group>
      </Table.Td>
      <Table.Td><Badge variant="outline" color="gray" size="sm" data-testid="file-rev">{a.revision ?? 1}</Badge></Table.Td>
      <Table.Td><Text size="xs">{fmtBytes(a.size)}</Text></Table.Td>
      <Table.Td><Text size="xs">{fmtDateTime(a.uploaded_at)}{uploader ? ` · ${uploader}` : ""}</Text></Table.Td>
      <Table.Td>
        {a.checked_out_by ? (
          <Tooltip label={tx("{v}since {checked_out_at}", { v: a.checkout_note ? `${a.checkout_note} — ` : "", checked_out_at: fmtDateTime(a.checked_out_at) })}>
            <Badge color={mine ? "teal" : "orange"} variant="light" leftSection={<IconLock size={11} />} data-testid="file-status">
              {mine ? tx("Checked out by you") : tx("Checked out · {display_name}", { display_name: a.checked_out_by.display_name })} · {fmtRelative(a.checked_out_at)}
            </Badge>
          </Tooltip>
        ) : <Text size="xs" c="dimmed" data-testid="file-status">{tx("Available")}</Text>}
      </Table.Td>
      <Table.Td>
        <input ref={input} type="file" hidden onChange={(e) => { const f = e.currentTarget.files?.[0]; if (f) setCheckin(f); e.currentTarget.value = ""; }}
          data-testid="file-checkin-input" />
        <Menu position="bottom-end" withinPortal>
          <Menu.Target><ActionIcon variant="subtle" color="gray" aria-label={tx("File actions")} data-testid="file-menu"><IconDots size={16} /></ActionIcon></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<IconDownload size={14} />} component="a" href={downloadUrl(base)}>{tx("Download")}</Menu.Item>
            <Menu.Item leftSection={<IconHistory size={14} />} onClick={onHistory} data-testid="file-history">{tx("Revision history")}</Menu.Item>
            {editable && !a.checked_out_by && (
              <Menu.Item leftSection={<IconLock size={14} />} onClick={() => checkout.mutate(undefined)} data-testid="file-checkout">{tx("Check out")}</Menu.Item>
            )}
            {editable && !lockedByOther && (
              <Menu.Item leftSection={<IconUpload size={14} />} onClick={() => input.current?.click()} data-testid="file-checkin">
                {mine ? tx("Check in new revision…") : tx("Upload new revision…")}
              </Menu.Item>
            )}
            {a.checked_out_by && (mine || can("manager")) && (
              <Menu.Item leftSection={<IconLockOpen size={14} />} onClick={() => cancel.mutate(undefined)} data-testid="file-cancel-checkout">
                {tx("Cancel check-out{v}", { v: mine ? "" : tx(" of {display_name}", { display_name: a.checked_out_by.display_name }) })}</Menu.Item>
            )}
            {editable && !lockedByOther && (
              <><Menu.Divider /><Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={() => remove.mutate(undefined)} data-testid="file-remove">{tx("Remove (kept in history)")}</Menu.Item></>
            )}
          </Menu.Dropdown>
        </Menu>
        <Modal opened={!!checkin} onClose={() => setCheckin(null)} title={tx("Check in {filename}", { filename: a.filename })}>
          <Stack>
            <Text size="sm">{tx("New content:")} <b>{checkin?.name}</b> ({fmtBytes(checkin?.size ?? 0)}{tx(") — becomes revision")} {(a.revision ?? 1) + 1}{mine ? tx(" and ends your check-out") : ""}.</Text>
            <TextInput label={tx("What changed?")} placeholder={tx("e.g. mounting holes added")} value={comment} onChange={(e) => setComment(e.currentTarget.value)} data-testid="file-checkin-comment" />
            <Group justify="flex-end"><Button onClick={() => submit.mutate(undefined)} loading={submit.isPending} data-testid="file-checkin-confirm">{tx("Check in")}</Button></Group>
          </Stack>
        </Modal>
      </Table.Td>
    </Table.Tr>
  );
}

function HistoryModal({ item, file, onClose }: { item: ItemDetail; file: Attachment | null; onClose: () => void }) {
  const { key } = useProjectCtx();
  const { data } = useFileHistory(key, item.key, file?.id ?? null);
  return (
    <Modal opened={!!file} onClose={onClose} size="lg" title={file ? tx("Revisions of {filename}", { filename: file.filename }) : ""}>
      <Table data-testid="file-history-table">
        <Table.Thead><Table.Tr><Table.Th>{tx("Rev")}</Table.Th><Table.Th>{tx("File")}</Table.Th><Table.Th>{tx("Item version")}</Table.Th><Table.Th>{tx("Checked in")}</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>
          {(data ?? []).map((r) => (
            <Table.Tr key={`${r.version_no}-${r.sha256}`}>
              <Table.Td><Badge variant="outline" color="gray" size="sm">{r.revision}</Badge></Table.Td>
              <Table.Td>
                <Anchor size="sm" href={downloadUrl(`/projects/${key}/items/${item.key}/attachments/${r.id}?version=${r.version_no}`)}>{r.filename}</Anchor>
                <Text size="xs" c="dimmed">{fmtBytes(r.size)}{r.comment ? ` · ${r.comment}` : ""}</Text>
              </Table.Td>
              <Table.Td><Text size="sm" className="mono">{r.item_version}</Text></Table.Td>
              <Table.Td><Text size="xs">{fmtDateTime(r.uploaded_at)}<br />{r.uploaded_by?.display_name}</Text></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Modal>
  );
}
