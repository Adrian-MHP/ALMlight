import { useState } from "react";
import { Alert, Badge, Button, Card, Code, CopyButton, Group, PasswordInput, SimpleGrid, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMe, useProjectMutation, useTokens } from "@/api/hooks";
import type { ApiToken } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { fmtDate, fmtDateTime } from "@/lib/format";

export function AccountPage() {
  const me = useMe().data!;
  const tokens = useTokens().data ?? [];
  const qc = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [tokenName, setTokenName] = useState("");
  const [created, setCreated] = useState<ApiToken | null>(null);
  const changePw = useProjectMutation(null, () => api.post("/auth/password", { current_password: current, new_password: next }),
    { success: "Password changed", onSuccess: () => { setCurrent(""); setNext(""); } });
  const createToken = useProjectMutation(null, () => api.post<ApiToken>("/auth/tokens", { name: tokenName }), {
    onSuccess: (t) => { setCreated(t); setTokenName(""); qc.invalidateQueries({ queryKey: ["tokens"] }); },
  });
  const revoke = useProjectMutation(null, (id: string) => api.del(`/auth/tokens/${id}`), {
    success: "Token revoked", onSuccess: () => qc.invalidateQueries({ queryKey: ["tokens"] }),
  });
  return (
    <>
      <PageHeader title="Account" subtitle={`${me.display_name} (${me.username})`} />
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder>
          <Title order={5} mb="sm">Change password</Title>
          <Stack>
            <PasswordInput label="Current password" value={current} onChange={(e) => setCurrent(e.currentTarget.value)} />
            <PasswordInput label="New password" description="At least 8 characters" value={next} onChange={(e) => setNext(e.currentTarget.value)} />
            <Button onClick={() => changePw.mutate(undefined)} disabled={!current || next.length < 8} loading={changePw.isPending}>Change password</Button>
          </Stack>
        </Card>
        <Card withBorder>
          <Title order={5} mb="xs">Personal API tokens</Title>
          <Text size="sm" c="dimmed" mb="sm">
            For scripts and integrations: send <Code>Authorization: Bearer &lt;token&gt;</Code>. Tokens act with your permissions.
          </Text>
          <Group align="flex-end">
            <TextInput label="Token name" placeholder="e.g. CI pipeline" value={tokenName} onChange={(e) => setTokenName(e.currentTarget.value)} style={{ flex: 1 }} />
            <Button onClick={() => createToken.mutate(undefined)} disabled={!tokenName.trim()} loading={createToken.isPending}>Create</Button>
          </Group>
          {created?.token && (
            <Alert color="teal" mt="sm" title="Copy your token now — it will not be shown again">
              <Group gap="xs" wrap="nowrap"><Code style={{ overflowWrap: "anywhere" }}>{created.token}</Code>
                <CopyButton value={created.token}>{({ copied, copy }) => <Button size="xs" onClick={copy}>{copied ? "Copied" : "Copy"}</Button>}</CopyButton>
              </Group>
            </Alert>
          )}
          <Table mt="sm">
            <Table.Tbody>
              {tokens.map((t) => (
                <Table.Tr key={t.id}>
                  <Table.Td><Text size="sm" fw={500}>{t.name}</Text><Text size="xs" c="dimmed" className="mono">{t.prefix}…</Text></Table.Td>
                  <Table.Td><Text size="xs">created {fmtDate(t.created_at)}<br />last used {fmtDateTime(t.last_used_at)}</Text></Table.Td>
                  <Table.Td>{t.revoked_at ? <Badge color="gray">revoked</Badge> :
                    <Button size="xs" variant="subtle" color="red" onClick={() => revoke.mutate(t.id)}>Revoke</Button>}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      </SimpleGrid>
    </>
  );
}
