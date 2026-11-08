import { useEffect, useRef, useState } from "react";
import {
  ActionIcon, Alert, Badge, Box, Button, Card, Code, Drawer, Group, Loader, Menu, ScrollArea, Select, Stack,
  Table, Text, Textarea, Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertTriangle, IconCheck, IconChevronDown, IconCirclesRelation, IconCpu, IconHistory, IconListSearch, IconMessage,
  IconPencil, IconPlus, IconReportSearch, IconRoute, IconSend, IconSparkles, IconTable, IconTrash, IconX,
} from "@tabler/icons-react";
import { useLocalStorage } from "@mantine/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, streamEvents } from "@/api/client";
import { pk } from "@/api/hooks";
import type { AssistantInfo, AssistantMessage, AssistantProposal, AssistantThread } from "@/api/types";
import { Markdown } from "@/components/Markdown";
import { fmtRelative } from "@/lib/format";
import { tx } from "@/lib/i18n";

/** What a tool did, in words — the chat shows this instead of the raw call. */
const TOOL_LABELS: Record<string, { label: string; icon: typeof IconListSearch }> = {
  project_overview: { label: tx("read the information model"), icon: IconTable },
  search_items: { label: tx("searched items"), icon: IconListSearch },
  get_item: { label: tx("read an item"), icon: IconReportSearch },
  coverage: { label: tx("computed the coverage"), icon: IconTable },
  impact: { label: tx("analysed the impact"), icon: IconRoute },
  history: { label: tx("read the history"), icon: IconHistory },
  create_item: { label: tx("create an item"), icon: IconPlus },
  update_item: { label: tx("change an item"), icon: IconPencil },
  create_link: { label: tx("link two items"), icon: IconCirclesRelation },
  add_comment: { label: tx("write a comment"), icon: IconMessage },
};

function toolInfo(name: string) {
  return TOOL_LABELS[name] ?? { label: name, icon: IconListSearch };
}

/** The assistant of the open project: it reads with the person's role and proposes changes they confirm. */
export function AssistantPanel({ projectKey, opened, onClose }: {
  projectKey: string; opened: boolean; onClose: () => void;
}) {
  const qc = useQueryClient();
  const [threadId, setThreadId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [wanted, setWanted] = useLocalStorage<string | null>({ key: "alm-assistant-model", defaultValue: null });
  const viewport = useRef<HTMLDivElement>(null);
  const base = `/projects/${projectKey}/assistant`;
  const info = useQuery<AssistantInfo>({
    queryKey: pk(projectKey, "assistant"), queryFn: () => api.get(base), enabled: opened,
  });
  const thread = useQuery<AssistantThread>({
    queryKey: pk(projectKey, "assistant", threadId), queryFn: () => api.get(`${base}/threads/${threadId}`),
    enabled: opened && !!threadId,
  });
  const show = (t: AssistantThread) => { setThreadId(t.id); qc.setQueryData(pk(projectKey, "assistant", t.id), t); };

  const start = useMutation<AssistantThread, ApiError>({
    mutationFn: () => api.post(`${base}/threads`, { model: wanted }),
    onSuccess: (t) => { show(t); qc.invalidateQueries({ queryKey: pk(projectKey, "assistant") }); },
  });
  // the answer is read while it is written: text in pieces, plus what the tools did
  const [live, setLive] = useState<{ text: string; tools: { name: string; ok: boolean }[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (path: string, body: unknown, changes = false) => {
    setBusy(true);
    setLive({ text: "", tools: [] });
    try {
      await streamEvents(path, body, (event) => {
        const kind = event.type;
        if (kind === "delta") setLive((l) => (l ? { ...l, text: l.text + String(event.text ?? "") } : l));
        else if (kind === "tool") setLive((l) => (l ? { ...l, tools: [...l.tools, { name: String(event.name), ok: event.ok !== false }] } : l));
        else if (kind === "done") show(event as unknown as AssistantThread);
        else if (kind === "error") notifications.show({ color: "red", title: tx("The assistant could not answer"), message: String(event.message ?? "") });
      });
      qc.invalidateQueries({ queryKey: pk(projectKey, "assistant") });
      if (changes) qc.invalidateQueries({ queryKey: ["p", projectKey] });  // applied changes touch the project
    } catch (err) {
      notifications.show({ color: "red", title: tx("The assistant could not answer"),
        message: err instanceof ApiError ? err.full : String(err) });
    } finally {
      setLive(null);
      setBusy(false);
    }
  };

  const ask = async (question: string) => {
    const id = threadId ?? (await api.post<AssistantThread>(`${base}/threads`, { model: wanted })).id;
    setThreadId(id);
    await run(`${base}/threads/${id}/stream`, { text: question });
  };
  const confirm = (approve: boolean) => run(`${base}/threads/${threadId}/confirm-stream`, { approve }, approve);
  const remove = useMutation<unknown, ApiError, string>({
    mutationFn: (id) => api.del(`${base}/threads/${id}`),
    onSuccess: (_r, id) => {
      if (id === threadId) setThreadId(null);
      qc.invalidateQueries({ queryKey: pk(projectKey, "assistant") });
    },
  });

  const messages = thread.data?.messages ?? [];
  const pending = thread.data?.pending ?? [];
  useEffect(() => {
    viewport.current?.scrollTo({ top: viewport.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, pending.length, busy]);

  const send = () => { if (text.trim() && !busy) { void ask(text.trim()); setText(""); } };

  return (
    <Drawer.Root opened={opened} onClose={onClose} position="right" size={520} padding="md">
      <Drawer.Overlay />
      <Drawer.Content data-testid="assistant-panel">
        <Drawer.Header>
          <Drawer.Title>
            <Group gap="xs">
              <IconSparkles size={18} />
              <Text fw={600}>{tx("Assistant")}</Text>
              {info.data?.model && <Badge size="xs" variant="light" style={{ textTransform: "none" }}>{info.data.model}</Badge>}
            </Group>
          </Drawer.Title>
          <Drawer.CloseButton />
        </Drawer.Header>
        <Drawer.Body style={{ height: "calc(100% - 60px)", display: "flex", flexDirection: "column", paddingBottom: 0 }}>
      {info.data && !info.data.enabled ? (
        <Alert color="gray" icon={<IconSparkles size={16} />} data-testid="assistant-off">
          <Text size="sm">{tx("The AI assistant is not switched on in this installation.")}</Text>
          <Text size="xs" c="dimmed" mt={6}>
            {tx("An administrator sets the language model in the configuration:")} <Code>ALMLIGHT_AZURE_OPENAI_ENDPOINT</Code>,{" "}
            <Code>ALMLIGHT_AZURE_OPENAI_API_KEY</Code>, <Code>ALMLIGHT_AZURE_OPENAI_DEPLOYMENT</Code>.
          </Text>
        </Alert>
      ) : (
        <>
          <Group justify="space-between" mb="xs">
            <Menu shadow="md" position="bottom-start" width={320}>
              <Menu.Target>
                <Button variant="subtle" size="xs" rightSection={<IconChevronDown size={14} />} data-testid="assistant-threads">
                  {thread.data?.title && thread.data.title !== "…" ? thread.data.title.slice(0, 40) : tx("New conversation")}
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item leftSection={<IconPlus size={14} />} onClick={() => start.mutate()}>{tx("New conversation")}</Menu.Item>
                {(info.data?.threads.length ?? 0) > 0 && <Menu.Label>{tx("Earlier")}</Menu.Label>}
                {info.data?.threads.map((t) => (
                  <Menu.Item key={t.id} onClick={() => setThreadId(t.id)}
                    rightSection={
                      <ActionIcon component="div" size="xs" variant="subtle" color="red" aria-label={tx("Delete conversation")}
                        onClick={(e) => { e.stopPropagation(); remove.mutate(t.id); }}><IconTrash size={12} /></ActionIcon>}>
                    <Text size="sm" lineClamp={1}>{t.title}</Text>
                    <Text size="xs" c="dimmed">{fmtRelative(t.updated_at)}</Text>
                  </Menu.Item>
                ))}
              </Menu.Dropdown>
            </Menu>
            <Group gap="xs">
              {info.data && !info.data.can_change && <Badge size="xs" variant="outline" color="gray">{tx("read only")}</Badge>}
              {(info.data?.models.length ?? 0) > 1 && (
                <Select size="xs" w={190} allowDeselect={false} data-testid="assistant-model"
                  aria-label={tx("Language model")} leftSection={<IconCpu size={14} />}
                  value={thread.data?.model ?? wanted ?? info.data?.models[0]?.id ?? null}
                  disabled={messages.length > 0}
                  onChange={(v) => { setWanted(v); if (messages.length) setThreadId(null); }}
                  data={info.data?.models.map((m) => ({ value: m.id, label: m.local ? `${m.label} (lokal)` : m.label }))} />
              )}
            </Group>
          </Group>
          <ScrollArea style={{ flex: 1 }} viewportRef={viewport} type="auto">
            <Stack gap="sm" pb="md" data-testid="assistant-messages">
              {messages.length === 0 && !busy && <Intro canChange={info.data?.can_change ?? false} onPick={(q) => void ask(q)} />}
              {messages.map((m) => <Message key={m.id} message={m} />)}
              {pending.map((p, n) => <Proposal key={n} proposal={p} />)}
              {pending.length > 0 && !busy && (
                <Group gap="xs" data-testid="assistant-confirm">
                  <Button size="xs" leftSection={<IconCheck size={14} />}
                    onClick={() => void confirm(true)} disabled={pending.every((p) => p.error)} data-testid="assistant-apply">
                    {tx("Apply")}
                  </Button>
                  <Button size="xs" variant="default" leftSection={<IconX size={14} />} onClick={() => void confirm(false)}
                    data-testid="assistant-discard">{tx("Discard")}</Button>
                </Group>
              )}
              {live?.tools.map((t, n) => {
                const { label, icon: Icon } = toolInfo(t.name);
                return (
                  <Group key={n} gap={6} wrap="nowrap">
                    <Icon size={13} color={t.ok ? "var(--mantine-color-dimmed)" : "var(--mantine-color-red-6)"} />
                    <Text size="xs" c={t.ok ? "dimmed" : "red"}>{label}</Text>
                  </Group>
                );
              })}
              {live?.text && (
                <Box className="assistant-answer" data-testid="assistant-streaming"><Markdown text={live.text} /></Box>
              )}
              {busy && !live?.text && (
                <Group gap="xs"><Loader size="xs" /><Text size="sm" c="dimmed">{tx("The assistant is working…")}</Text></Group>
              )}
            </Stack>
          </ScrollArea>
          <Box pt="xs" pb="md" style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}>
            <Group gap="xs" align="flex-end" wrap="nowrap">
              <Textarea style={{ flex: 1 }} autosize minRows={1} maxRows={6} value={text} data-testid="assistant-input"
                placeholder={tx("Ask about the project, or ask for a change…")} disabled={busy}
                onChange={(e) => setText(e.currentTarget.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
              <ActionIcon size={36} onClick={send} disabled={!text.trim() || busy} aria-label={tx("Send")} data-testid="assistant-send">
                <IconSend size={18} />
              </ActionIcon>
            </Group>
            <Text size="xs" c="dimmed" mt={4}>
              {info.data?.can_change ? tx("The assistant reads with your permissions; changes are applied only after you confirm them.")
                : tx("The assistant reads with your permissions and cannot change anything.")}
            </Text>
          </Box>
        </>
      )}
        </Drawer.Body>
      </Drawer.Content>
    </Drawer.Root>
  );
}

function Intro({ canChange, onPick }: { canChange: boolean; onPick: (q: string) => void }) {
  const examples = [
    tx("Which requirements have no test case?"),
    tx("Summarise the open change requests."),
    tx("What would change if SYS-1 changes?"),
    ...(canChange ? [tx("Add a requirement for salt spray resistance, 480 hours.")] : []),
  ];
  return (
    <Stack gap="xs">
      <Text size="sm" c="dimmed">{tx("The assistant knows this project: its items, links, states and history. It answers from the data, not from memory.")}</Text>
      {examples.map((e) => (
        <Button key={e} variant="default" size="xs" justify="flex-start" onClick={() => onPick(e)} styles={{ label: { whiteSpace: "normal" } }}>
          {e}
        </Button>
      ))}
    </Stack>
  );
}

function Message({ message }: { message: AssistantMessage }) {
  if (message.role === "tool") {
    const name = String(message.meta.name ?? "");
    const { label, icon: Icon } = toolInfo(name);
    const ok = message.meta.ok !== false;
    const applied = message.meta.applied === true;
    return (
      <Group gap={6} wrap="nowrap" data-testid={`assistant-tool-${name}`}>
        <Icon size={13} color={ok ? "var(--mantine-color-dimmed)" : "var(--mantine-color-red-6)"} />
        <Text size="xs" c={ok ? "dimmed" : "red"}>
          {applied ? tx("applied: {what}", { what: String(message.meta.summary ?? label) }) : label}
          {!ok && ` — ${shortError(message.content)}`}
        </Text>
      </Group>
    );
  }
  if (message.role === "user") {
    return (
      <Card withBorder padding="xs" bg="var(--mantine-color-default-hover)" data-testid="assistant-user">
        <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{message.content}</Text>
      </Card>
    );
  }
  if (!message.content) return null;
  return (
    <Box data-testid="assistant-answer" className="assistant-answer">
      <Markdown text={message.content} />
      {typeof message.meta.model === "string" && (
        <Text size="xs" c="dimmed" mt={2}>{String(message.meta.model)}</Text>
      )}
    </Box>
  );
}

function shortError(content: string): string {
  try {
    const parsed = JSON.parse(content);
    return String(parsed.error ?? parsed.not_executed ?? "").slice(0, 120);
  } catch {
    return "";
  }
}

/** A change the assistant wants to make: what it would do, exactly as the server previewed it. */
function Proposal({ proposal }: { proposal: AssistantProposal }) {
  const { label, icon: Icon } = toolInfo(proposal.name);
  const preview = proposal.preview as Record<string, unknown> | null;
  const before = preview?.before as Record<string, unknown> | undefined;
  const after = preview?.after as Record<string, unknown> | undefined;
  return (
    <Card withBorder padding="sm" data-testid="assistant-proposal">
      <Group gap={6} mb={4} wrap="nowrap">
        <Icon size={15} />
        <Text size="sm" fw={600}>{proposal.summary || label}</Text>
      </Group>
      {proposal.error ? (
        <Alert color="red" p="xs" icon={<IconAlertTriangle size={14} />}>
          <Text size="xs">{tx("This cannot be done: {reason}", { reason: proposal.error })}</Text>
        </Alert>
      ) : before && after ? (
        <Table verticalSpacing={2} fz="xs">
          <Table.Tbody>
            {changedRows(before, after).map(([field, from, to]) => (
              <Table.Tr key={field}>
                <Table.Td w={110}><Text size="xs" c="dimmed">{field}</Text></Table.Td>
                <Table.Td><Text size="xs" td="line-through" c="dimmed" lineClamp={2}>{from}</Text></Table.Td>
                <Table.Td><Text size="xs" lineClamp={2}>{to}</Text></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : (
        <Details values={proposal.arguments} />
      )}
    </Card>
  );
}

function changedRows(before: Record<string, unknown>, after: Record<string, unknown>): [string, string, string][] {
  const rows: [string, string, string][] = [];
  for (const key of ["title", "description"]) {
    if (String(before[key] ?? "") !== String(after[key] ?? "")) rows.push([key, String(before[key] ?? "—"), String(after[key] ?? "—")]);
  }
  const fieldsBefore = (before.fields ?? {}) as Record<string, unknown>;
  const fieldsAfter = (after.fields ?? {}) as Record<string, unknown>;
  for (const key of new Set([...Object.keys(fieldsBefore), ...Object.keys(fieldsAfter)])) {
    if (String(fieldsBefore[key] ?? "") !== String(fieldsAfter[key] ?? "")) {
      rows.push([key, String(fieldsBefore[key] ?? "—"), String(fieldsAfter[key] ?? "—")]);
    }
  }
  return rows;
}

/** The arguments of a proposal, flattened so that fields read as "priority: must" and not as JSON. */
function Details({ values }: { values: Record<string, unknown> }) {
  const rows: [string, string][] = [];
  for (const [key, value] of Object.entries(values)) {
    if (value === null || value === undefined || value === "") continue;
    if (typeof value === "object" && !Array.isArray(value)) {
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) rows.push([k, String(v)]);
    } else {
      rows.push([key, Array.isArray(value) ? value.join(", ") : String(value)]);
    }
  }
  return (
    <Stack gap={2}>
      {rows.map(([key, value], n) => (
        <Group key={`${key}-${n}`} gap={6} align="flex-start" wrap="nowrap">
          <Text size="xs" c="dimmed" w={90} style={{ flexShrink: 0 }}>{key}</Text>
          <Text size="xs" style={{ whiteSpace: "pre-wrap" }} lineClamp={4}>{value}</Text>
        </Group>
      ))}
    </Stack>
  );
}

/** Header button that opens the assistant for the project that is open. */
export function AssistantButton({ projectKey }: { projectKey?: string }) {
  const [opened, setOpened] = useState(false);
  useEffect(() => { setOpened(false); }, [projectKey]);
  if (!projectKey) return null;
  return (
    <>
      <Tooltip label={tx("Assistant")}>
        <ActionIcon variant="subtle" color="gray" size="lg" className="header-icon" onClick={() => setOpened(true)}
          aria-label={tx("Assistant")} data-testid="assistant-open"><IconSparkles size={20} /></ActionIcon>
      </Tooltip>
      {opened && <AssistantPanel projectKey={projectKey} opened={opened} onClose={() => setOpened(false)} />}
    </>
  );
}
