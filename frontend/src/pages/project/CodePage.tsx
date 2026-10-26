import { useState } from "react";
import {
  ActionIcon, Alert, Anchor, Badge, Breadcrumbs, Button, Card, Code, Group, Loader, Modal, PasswordInput, ScrollArea, Select,
  Stack, Switch, Table, Tabs, Text, TextInput, Tooltip,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import {
  IconArrowLeft, IconDownload, IconExternalLink, IconFile,
  IconFolder, IconGitBranch, IconGitCommit, IconPlus, IconRefresh, IconSearch, IconSettings, IconTag, IconTrash,
} from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, downloadUrl } from "@/api/client";
import { pk, useProjectMutation } from "@/api/hooks";
import type { BranchInfo, Commit, CommitDetail, FileView, Repo, TreeView } from "@/api/types";
import { ItemPicker } from "@/components/ItemPicker";
import { ProviderIcon } from "@/components/ProviderIcon";
import { PageHeader } from "@/components/PageHeader";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { tx } from "@/lib/i18n";
import { useProjectCtx } from "./ProjectLayout";

/** Git repositories of the project (Polarion repository browser): commits, diffs, files, branches. */
export function CodePage() {
  const { key, can } = useProjectCtx();
  const [params, setParams] = useSearchParams();
  const repos = useQuery<Repo[]>({ queryKey: pk(key, "repos"), queryFn: () => api.get(`/projects/${key}/repositories`) }).data;
  const [connecting, setConnecting] = useState(false);
  const [editing, setEditing] = useState<Repo | null>(null);
  const qc = useQueryClient();
  const repoId = params.get("repo") ?? repos?.[0]?.id ?? null;
  const repo = repos?.find((r) => r.id === repoId) ?? null;
  const tab = params.get("tab") ?? "commits";
  const commit = params.get("commit");
  const set = (patch: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) { if (v === null) p.delete(k); else p.set(k, v); }
    setParams(p);
  };
  const sync = useProjectMutation(key, () => api.post<Repo & { sync: { ok: boolean; new_commits?: number; error?: string } }>(`/projects/${key}/repositories/${repo!.id}/sync`), {
    success: (r) => r.sync.ok ? tx("{name}: {n} new commit(s)", { name: r.name, n: r.sync.new_commits ?? 0 }) : tx("Sync failed: {error}", { error: r.sync.error ?? "" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: pk(key, "repos") }),
  });
  if (!repos) return <Loader />;
  return (
    <>
      <PageHeader title={tx("Code")} subtitle={tx("Git repositories of the project: commits linked to items, diffs, files and branches")}
        actions={can("manager") && <Button leftSection={<IconPlus size={16} />} onClick={() => setConnecting(true)} data-testid="repo-connect">{tx("Connect repository")}</Button>} />
      {repos.length === 0 ? (
        <Card withBorder p="xl">
          <Stack align="center" gap="xs">
            <IconGitBranch size={36} />
            <Text fw={600}>{tx("No repository connected yet.")}</Text>
            <Text size="sm" c="dimmed" ta="center" maw={560}>{tx("Connect a GitHub, GitLab, Bitbucket, Azure Repos or any other Git repository. Commits whose message mentions an item key (e.g. “Fix SYS-12 range check”) become linked revisions of that item.")}</Text>
          </Stack>
        </Card>
      ) : repo && (
        <>
          <Card withBorder padding="sm" mb="sm">
            <Group justify="space-between" wrap="wrap" gap="xs">
              <Group gap="xs" wrap="wrap">
                {repos.length > 1 ? (
                  <Select size="xs" w={220} value={repo.id} allowDeselect={false} data-testid="repo-select"
                    data={repos.map((r) => ({ value: r.id, label: r.name }))} onChange={(v) => set({ repo: v, commit: null, path: null, ref: null })} />
                ) : <Group gap={6}><ProviderIcon provider={repo.provider} /><Text fw={600}>{repo.name}</Text></Group>}
                {repo.web_url ? <Anchor href={repo.web_url} target="_blank" rel="noopener noreferrer" size="xs">{repo.url}</Anchor> : <Text size="xs" c="dimmed">{repo.url}</Text>}
              </Group>
              <Group gap="xs">
                <Text size="xs" c="dimmed" data-testid="repo-status">
                  {tx("{commits} commits · {branches} branches · {tags} tags · synchronised {when}", { commits: repo.commit_count, branches: repo.branch_count, tags: repo.tag_count, when: repo.last_sync_at ? fmtRelative(repo.last_sync_at) : tx("never") })}
                </Text>
                {can("contributor") && <Tooltip label={tx("Fetch now")}><ActionIcon variant="default" onClick={() => sync.mutate(undefined)} loading={sync.isPending} aria-label={tx("Fetch now")} data-testid="repo-sync"><IconRefresh size={16} /></ActionIcon></Tooltip>}
                {can("manager") && <Tooltip label={tx("Repository settings")}><ActionIcon variant="default" onClick={() => setEditing(repo)} aria-label={tx("Repository settings")} data-testid="repo-settings"><IconSettings size={16} /></ActionIcon></Tooltip>}
              </Group>
            </Group>
            {repo.last_error && <Alert color="red" mt="xs" py={4}>{repo.last_error}</Alert>}
          </Card>
          {commit ? <CommitView repo={repo} sha={commit} onBack={() => set({ commit: null })} /> : (
            <Tabs value={tab} onChange={(v) => set({ tab: v, path: null })} keepMounted={false}>
              <Tabs.List mb="sm">
                <Tabs.Tab value="commits" leftSection={<IconGitCommit size={14} />} data-testid="code-tab-commits">{tx("Commits")}</Tabs.Tab>
                <Tabs.Tab value="files" leftSection={<IconFolder size={14} />} data-testid="code-tab-files">{tx("Files")}</Tabs.Tab>
                <Tabs.Tab value="branches" leftSection={<IconGitBranch size={14} />} data-testid="code-tab-branches">{tx("Branches & tags")}</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="commits"><CommitList repo={repo} onOpen={(sha) => set({ commit: sha })} /></Tabs.Panel>
              <Tabs.Panel value="files"><FilesBrowser repo={repo} path={params.get("path") ?? ""} gitRef={params.get("ref")} onNavigate={(path, ref) => set({ path: path || null, ref })} onCommit={(sha) => set({ commit: sha })} /></Tabs.Panel>
              <Tabs.Panel value="branches"><BranchList repo={repo} onOpen={(sha) => set({ commit: sha })} onBrowse={(ref) => set({ tab: "files", ref, path: null })} /></Tabs.Panel>
            </Tabs>
          )}
        </>
      )}
      {connecting && <ConnectRepo onClose={() => setConnecting(false)} onDone={(id) => { setConnecting(false); set({ repo: id }); }} />}
      {editing && <RepoSettings repo={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function ItemChips({ items }: { items?: { key: string; title: string; source?: string }[] }) {
  const { key } = useProjectCtx();
  if (!items?.length) return null;
  return (
    <Group gap={4} wrap="wrap">
      {items.map((i) => (
        <Tooltip key={i.key} label={i.title}>
          <Badge component={Link} to={`/p/${key}/items/${i.key}?tab=development`} variant={i.source === "manual" ? "outline" : "light"} size="sm"
            className="clickable badge-keep" style={{ textTransform: "none" }}>{i.key}</Badge>
        </Tooltip>
      ))}
    </Group>
  );
}

function CommitList({ repo, onOpen }: { repo: Repo; onOpen: (sha: string) => void }) {
  const { key } = useProjectCtx();
  const [q, setQ] = useState("");
  const [debounced] = useDebouncedValue(q, 300);
  const [ref, setRef] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);
  const refs = useQuery<Repo>({ queryKey: pk(key, "repo", repo.id), queryFn: () => api.get(`/projects/${key}/repositories/${repo.id}`) }).data?.refs ?? [];
  const params = new URLSearchParams({ limit: String(limit) });
  if (debounced) params.set("q", debounced);
  if (ref) params.set("ref", ref);
  const { data, isFetching } = useQuery<{ total: number; commits: Commit[] }>({
    queryKey: pk(key, "repo", repo.id, "commits", debounced, ref, limit),
    queryFn: () => api.get(`/projects/${key}/repositories/${repo.id}/commits?${params}`), placeholderData: (p) => p,
  });
  return (
    <Stack gap="sm">
      <Group gap="xs" wrap="wrap">
        <TextInput size="xs" w={300} leftSection={<IconSearch size={14} />} placeholder={tx("Message, author or hash…")} value={q} onChange={(e) => setQ(e.currentTarget.value)} data-testid="commit-search" />
        <Select size="xs" w={240} placeholder={tx("All branches")} clearable value={ref} onChange={setRef} searchable data-testid="commit-ref"
          data={refs.map((r) => ({ value: r.name, label: `${r.kind === "tag" ? "🏷 " : ""}${r.name}` }))} />
        {data && <Text size="xs" c="dimmed">{tx("{total} commit(s)", { total: data.total })}</Text>}
        {isFetching && <Loader size="xs" />}
      </Group>
      <Card withBorder padding={0}>
        <Table.ScrollContainer minWidth={760}>
          <Table highlightOnHover data-testid="commit-list">
            <Table.Thead><Table.Tr><Table.Th w={96}>{tx("Commit")}</Table.Th><Table.Th>{tx("Message")}</Table.Th><Table.Th w={180}>{tx("Items")}</Table.Th><Table.Th w={150}>{tx("Author")}</Table.Th><Table.Th w={140}>{tx("Date")}</Table.Th><Table.Th w={90} ta="right">{tx("Changes")}</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {data?.commits.map((c) => (
                <Table.Tr key={c.sha} data-testid={`commit-${c.short}`}>
                  <Table.Td><Anchor component="button" className="mono" size="sm" onClick={() => onOpen(c.sha)}>{c.short}</Anchor></Table.Td>
                  <Table.Td><Text size="sm" lineClamp={1} className="clickable" onClick={() => onOpen(c.sha)}>{c.title}</Text></Table.Td>
                  <Table.Td><ItemChips items={c.items} /></Table.Td>
                  <Table.Td><Text size="sm" truncate>{c.author}</Text></Table.Td>
                  <Table.Td><Tooltip label={fmtDateTime(c.committed_at)}><Text size="xs">{fmtRelative(c.committed_at)}</Text></Tooltip></Table.Td>
                  <Table.Td ta="right"><Text size="xs" className="mono"><span className="diff-add-text">+{c.additions}</span> <span className="diff-del-text">−{c.deletions}</span></Text></Table.Td>
                </Table.Tr>
              ))}
              {data && data.commits.length === 0 && <Table.Tr><Table.Td colSpan={6}><Text size="sm" c="dimmed">{tx("No commits match.")}</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>
      {data && data.total > data.commits.length && <Button variant="subtle" size="xs" onClick={() => setLimit((l) => l + 50)}>{tx("Show more")}</Button>}
    </Stack>
  );
}

const FILE_STATUS: Record<string, string> = { added: tx("added"), modified: tx("modified"), deleted: tx("deleted"), renamed: tx("renamed") };

export function DiffView({ patch }: { patch: string }) {
  const lines = patch.split("\n");
  return (
    <ScrollArea type="auto">
      <pre className="diff">
        {lines.map((l, i) => (
          <div key={i} className={l.startsWith("@@") ? "diff-hunk" : l.startsWith("+") ? "diff-add" : l.startsWith("-") ? "diff-del" : undefined}>{l || " "}</div>
        ))}
      </pre>
    </ScrollArea>
  );
}

function CommitView({ repo, sha, onBack }: { repo: Repo; sha: string; onBack: () => void }) {
  const { key, can } = useProjectCtx();
  const qc = useQueryClient();
  const [item, setItem] = useState<string | null>(null);
  const { data, error } = useQuery<CommitDetail>({ queryKey: pk(key, "repo", repo.id, "commit", sha), queryFn: () => api.get(`/projects/${key}/repositories/${repo.id}/commits/${sha}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: pk(key, "repo", repo.id) });
  const link = useProjectMutation(key, () => api.post(`/projects/${key}/items/${item}/revisions`, { repository: repo.id, sha }), {
    success: tx("Revision linked to {item}", { item: item ?? "" }), onSuccess: () => { setItem(null); refresh(); },
  });
  const unlink = useProjectMutation(key, (v: { key: string; link: string }) => api.del(`/projects/${key}/items/${v.key}/revisions/${v.link}`), {
    success: tx("Linked revision removed"), onSuccess: refresh,
  });
  if (error) return <Alert color="red">{String((error as Error).message)}</Alert>;
  if (!data) return <Loader />;
  const [title, ...body] = data.message.split("\n");
  return (
    <Stack gap="sm" data-testid="commit-view">
      <Group justify="space-between">
        <Button variant="subtle" size="xs" leftSection={<IconArrowLeft size={14} />} onClick={onBack} data-testid="commit-back">{tx("Commits")}</Button>
        {data.url && <Button size="xs" variant="default" component="a" href={data.url} target="_blank" rel="noopener noreferrer" leftSection={<ProviderIcon provider={repo.provider} size={14} />} rightSection={<IconExternalLink size={12} />}>{tx("Open in {provider}", { provider: repo.provider === "git" ? "Git" : repo.provider })}</Button>}
      </Group>
      <Card withBorder>
        <Text fw={700} size="lg">{title}</Text>
        {body.join("\n").trim() && <Text size="sm" mt={4} style={{ whiteSpace: "pre-wrap" }}>{body.join("\n").trim()}</Text>}
        <Group gap="lg" mt="sm" wrap="wrap">
          <Text size="xs" c="dimmed">{tx("{author} committed {date}", { author: data.author, date: fmtDateTime(data.committed_at) })}</Text>
          <Text size="xs" className="mono">{data.sha}</Text>
          {data.parents.length > 0 && <Text size="xs" c="dimmed">{tx("parent {parents}", { parents: data.parents.map((p) => p.slice(0, 8)).join(", ") })}</Text>}
          <Group gap={4}>{data.branches.map((b) => <Badge key={b} size="xs" variant="outline" leftSection={<IconGitBranch size={10} />} style={{ textTransform: "none" }}>{b}</Badge>)}</Group>
        </Group>
      </Card>
      <Card withBorder padding="sm">
        <Text size="sm" fw={600} mb={6}>{tx("Linked items")}</Text>
        <Group gap="xs" wrap="wrap" mb={can("contributor") ? "xs" : 0} data-testid="commit-items">
          {data.items?.length ? data.items.map((i) => (
            <Badge key={i.link_id} size="lg" variant={i.source === "manual" ? "outline" : "light"} style={{ textTransform: "none" }}
              rightSection={i.source === "manual" && can("contributor") ? <ActionIcon size="xs" variant="transparent" color="red" onClick={() => unlink.mutate({ key: i.key, link: i.link_id })} aria-label={tx("Remove link to {key}", { key: i.key })}><IconTrash size={10} /></ActionIcon> : undefined}>
              <Anchor component={Link} to={`/p/${key}/items/${i.key}?tab=development`} size="sm">{i.key}</Anchor> {i.title}
            </Badge>
          )) : <Text size="sm" c="dimmed">{tx("No item mentioned in the message.")}</Text>}
        </Group>
        {can("contributor") && (
          <Group align="flex-end" gap="xs">
            <ItemPicker label={tx("Link to an item")} value={item} onChange={setItem} w={340} testId="commit-link-item" />
            <Button size="sm" disabled={!item} onClick={() => link.mutate(undefined)} loading={link.isPending} data-testid="commit-link">{tx("Link")}</Button>
          </Group>
        )}
      </Card>
      <Text size="sm" fw={600}>{tx("{n} changed file(s)", { n: data.file_count })} <span className="diff-add-text">+{data.additions}</span> <span className="diff-del-text">−{data.deletions}</span></Text>
      {data.files.map((f) => (
        <Card withBorder padding={0} key={f.path} data-testid={`diff-${f.path}`}>
          <Group justify="space-between" px="sm" py={6} className="diff-file-head">
            <Group gap={6}><IconFile size={14} /><Text size="sm" className="mono">{f.status === "renamed" ? `${f.old_path} → ${f.path}` : f.path}</Text>
              <Badge size="xs" variant="light" color={f.status === "added" ? "teal" : f.status === "deleted" ? "red" : "gray"}>{FILE_STATUS[f.status] ?? f.status}</Badge></Group>
            <Text size="xs" className="mono"><span className="diff-add-text">+{f.additions}</span> <span className="diff-del-text">−{f.deletions}</span></Text>
          </Group>
          {f.binary ? <Text size="xs" c="dimmed" p="sm">{tx("Binary file")}</Text> : <DiffView patch={f.patch} />}
        </Card>
      ))}
      {data.truncated && <Alert color="yellow">{tx("The diff is too large to show completely.")}</Alert>}
    </Stack>
  );
}

function FilesBrowser({ repo, path, gitRef, onNavigate, onCommit }: {
  repo: Repo; path: string; gitRef: string | null; onNavigate: (path: string, ref: string | null) => void; onCommit: (sha: string) => void;
}) {
  const { key } = useProjectCtx();
  const refs = useQuery<Repo>({ queryKey: pk(key, "repo", repo.id), queryFn: () => api.get(`/projects/${key}/repositories/${repo.id}`) }).data?.refs ?? [];
  // folders end with "/" (set by the tree and the breadcrumbs), everything else is a file
  const isFile = path !== "" && !path.endsWith("/");
  const q = new URLSearchParams({ path });
  if (gitRef) q.set("ref", gitRef);
  const dirPath = isFile ? path.split("/").slice(0, -1).join("/") : path.replace(/\/$/, "");
  const dq = new URLSearchParams({ path: dirPath });
  if (gitRef) dq.set("ref", gitRef);
  const tree = useQuery<TreeView>({ queryKey: pk(key, "repo", repo.id, "tree", gitRef, dirPath), queryFn: () => api.get(`/projects/${key}/repositories/${repo.id}/tree?${dq}`) });
  const file = useQuery<FileView>({ queryKey: pk(key, "repo", repo.id, "file", gitRef, path), queryFn: () => api.get(`/projects/${key}/repositories/${repo.id}/file?${q}`), enabled: isFile });
  const parts = path.split("/").filter(Boolean);
  const current = gitRef ?? tree.data?.ref ?? repo.default_branch ?? "HEAD";
  return (
    <Stack gap="sm">
      <Group gap="xs" wrap="wrap">
        <Select size="xs" w={240} value={current} allowDeselect={false} searchable data-testid="files-ref" leftSection={<IconGitBranch size={14} />}
          data={Array.from(new Set([current, ...refs.map((r) => r.name)]))} onChange={(v) => onNavigate(path, v)} />
        <Breadcrumbs separator="/">
          <Anchor component="button" size="sm" onClick={() => onNavigate("", gitRef)}>{repo.name}</Anchor>
          {parts.map((p, i) => <Anchor key={i} component="button" size="sm" onClick={() => onNavigate(parts.slice(0, i + 1).join("/") + (isFile && i === parts.length - 1 ? "" : "/"), gitRef)}>{p}</Anchor>)}
        </Breadcrumbs>
      </Group>
      {tree.error && <Alert color="red">{String((tree.error as Error).message)}</Alert>}
      {isFile ? (
        file.data ? (
          <Card withBorder padding={0} data-testid="file-view">
            <Group justify="space-between" px="sm" py={6} className="diff-file-head">
              <Text size="sm" className="mono">{file.data.path} <Text span size="xs" c="dimmed">{tx("{size} bytes", { size: file.data.size })}</Text></Text>
              <Group gap="xs">
                <Button size="compact-xs" variant="default" component="a" href={downloadUrl(`/projects/${key}/repositories/${repo.id}/raw?${q}`)} leftSection={<IconDownload size={12} />}>{tx("Download")}</Button>
                {file.data.url && <Button size="compact-xs" variant="default" component="a" href={file.data.url} target="_blank" rel="noopener noreferrer" rightSection={<IconExternalLink size={12} />}>{tx("Open in {provider}", { provider: repo.provider })}</Button>}
              </Group>
            </Group>
            {file.data.text !== null ? (
              <ScrollArea type="auto" mah="70vh">
                <pre className="code-view">{file.data.text.split("\n").map((l, i) => <div key={i}><span className="code-ln">{i + 1}</span>{l || " "}</div>)}</pre>
              </ScrollArea>
            ) : <Text size="sm" c="dimmed" p="sm">{file.data.binary ? tx("Binary file — use Download.") : tx("The file is too large to show — use Download.")}</Text>}
            <Stack gap={2} p="sm">
              <Text size="xs" fw={600}>{tx("History")}</Text>
              {file.data.history.map((c) => (
                <Group key={c.sha} gap="xs" wrap="nowrap">
                  <Anchor component="button" size="xs" className="mono" onClick={() => onCommit(c.sha)}>{c.short}</Anchor>
                  <Text size="xs" truncate>{c.title}</Text><Text size="xs" c="dimmed">{c.author} · {fmtRelative(c.committed_at)}</Text>
                </Group>
              ))}
            </Stack>
          </Card>
        ) : file.error ? <Alert color="red">{String((file.error as Error).message)}</Alert> : <Loader size="sm" />
      ) : tree.data && (
        <Card withBorder padding={0}>
          {tree.data.commit && (
            <Group px="sm" py={6} gap="xs" className="diff-file-head" wrap="nowrap">
              <Anchor component="button" size="xs" className="mono" onClick={() => onCommit(tree.data!.commit!.sha)}>{tree.data.commit.short}</Anchor>
              <Text size="xs" truncate>{tree.data.commit.title}</Text><Text size="xs" c="dimmed">{tree.data.commit.author} · {fmtRelative(tree.data.commit.committed_at)}</Text>
            </Group>
          )}
          <Table highlightOnHover data-testid="file-tree">
            <Table.Tbody>
              {tree.data.entries.map((e) => (
                <Table.Tr key={e.path} className="clickable" onClick={() => e.kind !== "submodule" && onNavigate(e.kind === "dir" ? `${e.path}/` : e.path, gitRef)} data-testid={`tree-${e.name}`}>
                  <Table.Td w={28}>{e.kind === "dir" ? <IconFolder size={16} color="var(--mantine-color-yellow-7)" /> : <IconFile size={16} />}</Table.Td>
                  <Table.Td><Text size="sm">{e.name}</Text></Table.Td>
                  <Table.Td w={110} ta="right"><Text size="xs" c="dimmed">{e.size != null ? tx("{size} bytes", { size: e.size }) : ""}</Text></Table.Td>
                </Table.Tr>
              ))}
              {tree.data.entries.length === 0 && <Table.Tr><Table.Td><Text size="sm" c="dimmed">{tx("Empty folder.")}</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </Stack>
  );
}

function BranchList({ repo, onOpen, onBrowse }: { repo: Repo; onOpen: (sha: string) => void; onBrowse: (ref: string) => void }) {
  const { key } = useProjectCtx();
  const data = useQuery<BranchInfo[]>({ queryKey: pk(key, "repo", repo.id, "branches"), queryFn: () => api.get(`/projects/${key}/repositories/${repo.id}/branches`) }).data;
  if (!data) return <Loader size="sm" />;
  return (
    <Card withBorder padding={0}>
      <Table.ScrollContainer minWidth={700}>
        <Table data-testid="branch-list">
          <Table.Thead><Table.Tr><Table.Th>{tx("Name")}</Table.Th><Table.Th w={200}>{tx("Items")}</Table.Th><Table.Th>{tx("Last commit")}</Table.Th><Table.Th w={80} /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {data.map((b) => (
              <Table.Tr key={`${b.kind}-${b.name}`} data-testid={`branch-${b.name}`}>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">{b.kind === "tag" ? <IconTag size={14} /> : <IconGitBranch size={14} />}
                    <Anchor component="button" size="sm" className="mono" onClick={() => onBrowse(b.name)}>{b.name}</Anchor>
                    {b.default && <Badge size="xs" variant="light">{tx("default")}</Badge>}</Group>
                </Table.Td>
                <Table.Td><ItemChips items={b.items} /></Table.Td>
                <Table.Td>{b.head ? <Group gap="xs" wrap="nowrap"><Anchor component="button" size="xs" className="mono" onClick={() => onOpen(b.head!.sha)}>{b.head.short}</Anchor><Text size="xs" truncate>{b.head.title}</Text><Text size="xs" c="dimmed">{fmtRelative(b.head.committed_at)}</Text></Group> : <Text size="xs" className="mono">{b.sha.slice(0, 8)}</Text>}</Table.Td>
                <Table.Td>{b.url && <ActionIcon variant="subtle" component="a" href={b.url} target="_blank" rel="noopener noreferrer" aria-label={tx("Open in {provider}", { provider: repo.provider })}><IconExternalLink size={14} /></ActionIcon>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  );
}

function ConnectRepo({ onClose, onDone }: { onClose: () => void; onDone: (id: string) => void }) {
  const { key } = useProjectCtx();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [user, setUser] = useState("");
  const guess = url.replace(/\.git$/, "").split("/").filter(Boolean).pop() ?? "";
  const add = useProjectMutation(key, () => api.post<Repo & { sync: { new_commits?: number; linked?: number } }>(`/projects/${key}/repositories`, { name: name || guess, url, token: token || null, auth_user: user || null }), {
    success: (r) => tx("{name} connected: {n} commit(s), {linked} linked to items", { name: r.name, n: r.sync.new_commits ?? 0, linked: r.sync.linked ?? 0 }),
    onSuccess: (r) => onDone(r.id),
  });
  return (
    <Modal opened onClose={onClose} title={tx("Connect a Git repository")} size="lg">
      <Stack data-testid="repo-connect-modal">
        <TextInput label={tx("Clone URL")} placeholder="https://github.com/owner/repository.git" value={url} onChange={(e) => setUrl(e.currentTarget.value)} required data-testid="repo-url"
          description={tx("HTTPS URL of GitHub, GitLab, Bitbucket, Azure Repos or any Git server")} />
        <TextInput label={tx("Name")} placeholder={guess} value={name} onChange={(e) => setName(e.currentTarget.value)} data-testid="repo-name" />
        <PasswordInput label={tx("Access token (optional)")} value={token} onChange={(e) => setToken(e.currentTarget.value)} data-testid="repo-token"
          description={tx("Needed for private repositories (read) and for creating branches (write). Stored encrypted; it is never shown again.")} />
        <TextInput label={tx("User name for the token (Bitbucket only)")} value={user} onChange={(e) => setUser(e.currentTarget.value)} />
        <Text size="xs" c="dimmed">{tx("The server keeps a read-only mirror and fetches it every few minutes; a push webhook (Settings → Integrations) makes it fetch immediately.")}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button onClick={() => add.mutate(undefined)} disabled={!url || !(name || guess)} loading={add.isPending} data-testid="repo-connect-save">{tx("Connect")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function RepoSettings({ repo, onClose }: { repo: Repo; onClose: () => void }) {
  const { key } = useProjectCtx();
  const qc = useQueryClient();
  const [name, setName] = useState(repo.name);
  const [token, setToken] = useState("");
  const [enabled, setEnabled] = useState(repo.enabled);
  const save = useProjectMutation(key, (v: { clear_token?: boolean }) => api.patch(`/projects/${key}/repositories/${repo.id}`, { name, token: token || null, enabled, ...v }), {
    success: tx("Repository saved"), onSuccess: () => { qc.invalidateQueries({ queryKey: pk(key, "repos") }); onClose(); },
  });
  const remove = useProjectMutation(key, () => api.del(`/projects/${key}/repositories/${repo.id}`), {
    success: tx("Repository disconnected"), onSuccess: () => { qc.invalidateQueries({ queryKey: pk(key, "repos") }); onClose(); },
  });
  return (
    <Modal opened onClose={onClose} title={tx("Repository settings")}>
      <Stack>
        <TextInput label={tx("Name")} value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Text size="xs">{tx("Clone URL")}: <Code>{repo.url}</Code></Text>
        <PasswordInput label={repo.has_token ? tx("Replace the access token") : tx("Access token (optional)")} value={token} onChange={(e) => setToken(e.currentTarget.value)} />
        {repo.has_token && <Button size="xs" variant="subtle" color="red" onClick={() => save.mutate({ clear_token: true })}>{tx("Remove the stored token")}</Button>}
        <Switch label={tx("Fetch automatically")} checked={enabled} onChange={(e) => setEnabled(e.currentTarget.checked)} />
        <Group justify="space-between">
          <Button color="red" variant="subtle" leftSection={<IconTrash size={14} />} onClick={() => remove.mutate(undefined)} data-testid="repo-disconnect">{tx("Disconnect")}</Button>
          <Button onClick={() => save.mutate({})} loading={save.isPending}>{tx("Save")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
