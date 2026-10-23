import { useState } from "react";
import {
  Alert, Badge, Button, Checkbox, Group, Modal, SegmentedControl, Stack, Table, Text, TextInput, Textarea,
} from "@mantine/core";
import { IconArrowLeft, IconArrowRight, IconGitBranch, IconGitMerge } from "@tabler/icons-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useItemBranches, useMergePreview, useProjectMutation } from "@/api/hooks";
import type { BranchInfo, MergePreview } from "@/api/types";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "./ProjectLayout";
import { tx } from "@/lib/i18n";

const STATUS: Record<MergePreview["pairs"][number]["status"], { color: string; label: string }> = {
  conflict: { color: "red", label: tx("conflict") },
  both_changed: { color: "grape", label: tx("both changed") },
  branch_changed: { color: "indigo", label: tx("changed in branch") },
  source_changed: { color: "teal", label: tx("changed in source") },
  deleted_in_branch: { color: "gray", label: tx("deleted in branch") },
  deleted_in_source: { color: "gray", label: tx("deleted in source") },
  unchanged: { color: "gray", label: tx("unchanged") },
};

/** Banner on a document: the branch it belongs to or the branches made from it, with compare & merge. */
export function BranchBar({ docKey, creating, onCloseCreate }: { docKey: string; creating: boolean; onCloseCreate: () => void }) {
  const { key } = useProjectCtx();
  const branches = useItemBranches(key, docKey).data ?? [];
  const [merging, setMerging] = useState<BranchInfo | null>(null);
  const isBranch = branches.find((b) => b.branch_root === docKey);
  const children = branches.filter((b) => b.source_root === docKey);
  return (
    <>
      {isBranch && (
        <Alert color="indigo" mb="md" icon={<IconGitBranch size={18} />} data-testid="branch-banner"
          title={<>{tx("Branch “")}{isBranch.name}{tx("” of")} <Link to={`/p/${key}/documents/${isBranch.source_root}`}>{isBranch.source_root}</Link></>}>
          <Group justify="space-between">
            <Text size="sm">{tx("Created {created_at}{v}", { created_at: fmtDateTime(isBranch.created_at), v: isBranch.last_merged_at ? tx(" · last merge {last_merged_at}", { last_merged_at: fmtDateTime(isBranch.last_merged_at) }) : "" })}</Text>
            <Button size="xs" leftSection={<IconGitMerge size={14} />} onClick={() => setMerging(isBranch)} data-testid="open-merge">{tx("Compare & merge")}</Button>
          </Group>
        </Alert>
      )}
      {children.length > 0 && (
        <Alert color="gray" mb="md" icon={<IconGitBranch size={18} />} title={tx("Branches of this document")}>
          <Stack gap={4}>
            {children.map((b) => (
              <Group key={b.id} gap="xs">
                <Link to={`/p/${key}/documents/${b.branch_root}`} className="item-key">{b.branch_root}</Link>
                <Text size="sm">{b.name}</Text>
                <Button size="compact-xs" variant="subtle" onClick={() => setMerging(b)}>{tx("Compare & merge")}</Button>
              </Group>
            ))}
          </Stack>
        </Alert>
      )}
      <CreateBranchModal opened={creating} onClose={onCloseCreate} docKey={docKey} />
      {merging && <MergeModal branch={merging} onClose={() => setMerging(null)} />}
    </>
  );
}

function CreateBranchModal({ opened, onClose, docKey }: { opened: boolean; onClose: () => void; docKey: string }) {
  const { key } = useProjectCtx();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = useProjectMutation(key, () => api.post<BranchInfo>(`/projects/${key}/items/${docKey}/branch`, { name, description }), {
    success: (b) => tx("Branch {branch_root} created", { branch_root: b.branch_root }),
    onSuccess: (b) => { onClose(); setName(""); navigate(`/p/${key}/documents/${b.branch_root}`); },
  });
  return (
    <Modal opened={opened} onClose={onClose} title={tx("Branch {docKey}", { docKey: docKey })}>
      <Stack>
        <Text size="sm" c="dimmed">
          {tx("Copies the document with all headings and items into new items (with their traces). Work on the branch independently, then merge changes back with a 3-way comparison — or pull later source changes into the branch.")}
        </Text>
        <TextInput label={tx("Branch name")} placeholder={tx("e.g. Customer variant X / Release 2.0")} value={name} onChange={(e) => setName(e.currentTarget.value)}
          required data-testid="branch-name" />
        <Textarea label={tx("Purpose")} value={description} onChange={(e) => setDescription(e.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button onClick={() => create.mutate(undefined)} disabled={!name.trim()} loading={create.isPending} data-testid="branch-create">{tx("Create branch")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

const fmt = (v: unknown) => (v === null || v === undefined || v === "" ? "∅" : Array.isArray(v) ? v.join(", ") : String(v));

function MergeModal({ branch, onClose }: { branch: BranchInfo; onClose: () => void }) {
  const { key, can } = useProjectCtx();
  const { data } = useMergePreview(key, branch.id);
  const [resolutions, setResolutions] = useState<Record<string, Record<string, string>>>({});
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const merge = useProjectMutation(key, (direction: string) => {
    const selectable = [...(data?.pairs.map((p) => p.branch) ?? []), ...(data?.added_in_branch.map((a) => a.branch) ?? [])];
    return api.post<{ updated: string[]; created: string[] }>(`/projects/${key}/branches/${branch.id}/merge`, {
      direction, resolutions, items: selectable.filter((k) => !excluded.has(k)),
    });
  }, { success: (r) => tx("Merged: {length} updated, {length1} created", { length: r.updated.length, length1: r.created.length }) });
  const pending = data?.pairs.filter((p) => p.status !== "unchanged") ?? [];
  const toggle = (k: string) => setExcluded((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  return (
    <Modal opened onClose={onClose} size="90%" title={<Group gap="xs"><IconGitMerge size={18} /><Text fw={600}>{branch.name}: {branch.branch_root} ⇄ {branch.source_root}</Text></Group>}>
      {!data ? <Text>{tx("Loading…")}</Text> : (
        <Stack data-testid="merge-dialog">
          <Text size="sm" c="dimmed">
            {tx("Field-level 3-way comparison against the common ancestor. Changes on one side merge automatically; conflicts need a decision. Merging writes new versions — released targets must be revised first.")}
          </Text>
          {pending.length === 0 && data.added_in_branch.length === 0 && <Alert color="green">{tx("Branch and source are in sync.")}</Alert>}
          {pending.length > 0 && (
            <Table>
              <Table.Thead><Table.Tr><Table.Th w={30} /><Table.Th>{tx("Branch item")}</Table.Th><Table.Th>{tx("Source item")}</Table.Th><Table.Th>{tx("Status")}</Table.Th><Table.Th>{tx("Changes")}</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {pending.map((p) => (
                  <Table.Tr key={p.branch} data-testid={`merge-row-${p.branch}`}>
                    <Table.Td><Checkbox checked={!excluded.has(p.branch)} onChange={() => toggle(p.branch)} aria-label={tx("include")} /></Table.Td>
                    <Table.Td><Link to={`/p/${key}/items/${p.branch}`} className="item-key">{p.branch}</Link> <Text span size="xs" className="mono">{p.branch_version}</Text><Text size="xs" lineClamp={1}>{p.title}</Text></Table.Td>
                    <Table.Td><Link to={`/p/${key}/items/${p.source}`} className="item-key">{p.source}</Link> <Text span size="xs" className="mono">{p.source_version}</Text></Table.Td>
                    <Table.Td><Badge color={STATUS[p.status].color} variant="light">{STATUS[p.status].label}</Badge></Table.Td>
                    <Table.Td>
                      <Stack gap={6}>
                        {p.changes.filter((c) => c.kind !== "same").map((c) => (
                          <Group key={c.field} gap="xs" wrap="nowrap" align="flex-start">
                            <Text size="xs" fw={600} w={120} style={{ flexShrink: 0 }}>{c.field}</Text>
                            {c.kind === "conflict" ? (
                              <SegmentedControl size="xs" value={resolutions[p.branch]?.[c.field] ?? ""} data-testid={`resolve-${p.branch}-${c.field}`}
                                onChange={(v) => setResolutions((r) => ({ ...r, [p.branch]: { ...(r[p.branch] ?? {}), [c.field]: v } }))}
                                data={[{ value: "branch", label: tx("branch: {branch}", { branch: fmt(c.branch).slice(0, 40) }) }, { value: "source", label: tx("source: {source}", { source: fmt(c.source).slice(0, 40) }) }]} />
                            ) : (
                              <Text size="xs">
                                <Badge size="xs" variant="outline" mr={4}>{c.kind}</Badge>
                                <span className="diff-del">{fmt(c.base).slice(0, 60)}</span> → <span className="diff-add">{fmt(c.kind === "branch" ? c.branch : c.source).slice(0, 60)}</span>
                              </Text>
                            )}
                          </Group>
                        ))}
                      </Stack>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
          {data.added_in_branch.length > 0 && (
            <Stack gap={4}>
              <Text size="sm" fw={600}>{tx("New in branch (created in the source on merge)")}</Text>
              {data.added_in_branch.map((a) => (
                <Group key={a.branch} gap="xs">
                  <Checkbox checked={!excluded.has(a.branch)} onChange={() => toggle(a.branch)} aria-label={tx("include")} />
                  <Text className="item-key" size="sm">{a.branch}</Text><Text size="sm">{a.title}</Text>
                  <Text size="xs" c="dimmed">{a.parent_in_source ? tx("→ below {parent_in_source}", { parent_in_source: a.parent_in_source }) : tx("parent not in source — skipped")}</Text>
                </Group>
              ))}
            </Stack>
          )}
          {can("contributor") && (pending.length > 0 || data.added_in_branch.length > 0) && (
            <Group justify="flex-end">
              <Button variant="light" leftSection={<IconArrowLeft size={16} />} onClick={() => merge.mutate("from_source")} loading={merge.isPending && merge.variables === "from_source"}
                data-testid="merge-from-source">{tx("Update branch from source")}</Button>
              <Button leftSection={<IconArrowRight size={16} />} onClick={() => merge.mutate("to_source")} loading={merge.isPending && merge.variables === "to_source"}
                data-testid="merge-to-source">{tx("Merge into source")}</Button>
            </Group>
          )}
        </Stack>
      )}
    </Modal>
  );
}
