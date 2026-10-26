import { useState } from "react";
import { Badge, Group, Loader, Select, Text } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconGitCommit } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError, qs } from "@/api/client";
import { pk } from "@/api/hooks";
import type { Commit } from "@/api/types";
import { NO_FILL } from "@/lib/forms";
import { fmtRelative } from "@/lib/format";
import { tx } from "@/lib/i18n";

/** Pick a commit of a connected repository instead of typing its hash: the list searches the indexed commits of
 *  the repository (message, author, hash) on the server, optionally only those of one branch or tag. Commits
 *  already linked to ``linkedTo`` cannot be picked twice. */
export function CommitPicker({ projectKey, repoId, gitRef, value, onChange, linkedTo, label, w = 340, size = "xs", testId }: {
  projectKey: string;
  repoId: string;
  gitRef?: string | null;
  value: string | null;
  onChange: (sha: string | null) => void;
  /** Item key whose commits are already linked (those entries are shown but cannot be chosen again). */
  linkedTo?: { key: string; shas: string[] };
  label?: string;
  w?: number | string;
  size?: string;
  testId?: string;
}) {
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search.trim(), 250);
  const query = qs({ limit: 25, q: debounced || undefined, ref: gitRef || undefined });
  const commits = useQuery<{ total: number; commits: Commit[] }, ApiError>({
    queryKey: pk(projectKey, "repo", repoId, "pick", gitRef ?? "", debounced),
    queryFn: () => api.get(`/projects/${projectKey}/repositories/${repoId}/commits${query}`),
    retry: false,
    placeholderData: (previous) => previous,
  });
  const rows = commits.data?.commits ?? [];
  const meta = new Map(rows.map((c) => [c.sha, c]));
  const linked = new Set(linkedTo?.shas ?? []);
  return (
    <Select
      label={label ?? tx("Commit")}
      placeholder={tx("search message, author or hash…")}
      size={size}
      w={w}
      searchable
      clearable
      value={value}
      onChange={onChange}
      searchValue={search}
      onSearchChange={setSearch}
      filter={({ options }) => options}   // the server has already searched and ordered the commits
      nothingFoundMessage={commits.error ? commits.error.message : commits.isFetching ? tx("Searching…") : tx("No commit found")}
      rightSection={commits.isFetching ? <Loader size={12} /> : undefined}
      leftSection={<IconGitCommit size={14} />}
      maxDropdownHeight={320}
      comboboxProps={{ width: 460, position: "bottom-start" }}
      data={rows.map((c) => ({ value: c.sha, label: `${c.short} ${c.title}`, disabled: linked.has(c.sha) }))}
      renderOption={({ option }) => {
        const c = meta.get(option.value);
        if (!c) return <Text size="sm">{option.label}</Text>;
        return (
          <div style={{ minWidth: 0 }}>
            <Group gap={6} wrap="nowrap">
              <Text size="xs" className="mono" c="dimmed">{c.short}</Text>
              <Text size="sm" lineClamp={1}>{c.title}</Text>
              {linked.has(c.sha) && <Badge size="xs" variant="light" ml="auto" style={{ flexShrink: 0 }}>{tx("already linked")}</Badge>}
            </Group>
            <Text size="xs" c="dimmed" lineClamp={1}>
              {c.author} · {fmtRelative(c.committed_at)}
              {c.items?.length ? ` · ${c.items.map((i) => i.key).join(", ")}` : ""}
            </Text>
          </div>
        );
      }}
      data-testid={testId}
      {...NO_FILL}
    />
  );
}
