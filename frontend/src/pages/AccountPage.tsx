import { useState } from "react";
import { Alert, Badge, Button, Card, Code, CopyButton, Group, PasswordInput, SegmentedControl, SimpleGrid, Stack, Switch, Table, Text, TextInput, Title } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMe, useNotifications, useProjectMutation, useTokens } from "@/api/hooks";
import type { ApiToken } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { fmtDate, fmtDateTime } from "@/lib/format";
import { chooseLanguage, LOCALES, locale, tx, type Locale } from "@/lib/i18n";

export function AccountPage() {
  const me = useMe().data!;
  const tokens = useTokens().data ?? [];
  const qc = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [tokenName, setTokenName] = useState("");
  const [created, setCreated] = useState<ApiToken | null>(null);
  const changePw = useProjectMutation(null, () => api.post("/auth/password", { current_password: current, new_password: next }),
    { success: tx("Password changed"), onSuccess: () => { setCurrent(""); setNext(""); } });
  const createToken = useProjectMutation(null, () => api.post<ApiToken>("/auth/tokens", { name: tokenName }), {
    onSuccess: (t) => { setCreated(t); setTokenName(""); qc.invalidateQueries({ queryKey: ["tokens"] }); },
  });
  const revoke = useProjectMutation(null, (id: string) => api.del(`/auth/tokens/${id}`), {
    success: tx("Token revoked"), onSuccess: () => qc.invalidateQueries({ queryKey: ["tokens"] }),
  });
  const notes = useNotifications().data;
  const setEmail = useProjectMutation(null, (on: boolean) => api.put("/notifications/preferences", { email_notifications: on }),
    { success: tx("Saved"), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  return (
    <>
      <PageHeader title={tx("Account")} subtitle={`${me.display_name} (${me.username})`} />
      <Card withBorder mb="md">
        <Title order={5} mb="xs">{tx("Notifications")}</Title>
        <Text size="sm" c="dimmed" mb="sm">{tx("You are notified about items you own or watch, approvals you can give and comments that mention you (@{username}).", { username: me.username })}</Text>
        <Switch label={notes?.email ? tx("Also send an e-mail digest{v}", { v: me.email ? tx(" to {email}", { email: me.email }) : tx(" (no e-mail address on file)") }) : tx("E-mail digests (not configured on this server)")}
          disabled={!notes?.email} checked={!!notes?.email_notifications && !!notes?.email}
          onChange={(e) => setEmail.mutate(e.currentTarget.checked)} data-testid="email-notifications" />
      </Card>
      <Card withBorder mb="md">
        <Title order={5} mb="xs">{tx("Language")}</Title>
        <Text size="sm" c="dimmed" mb="sm">{tx("The language of the user interface, dates and numbers. It is saved with your account and also used for e-mail digests and exports.")}</Text>
        <SegmentedControl value={locale()} data={LOCALES} data-testid="account-language"
          onChange={(v) => chooseLanguage(v as Locale, (l) => api.put("/auth/me/locale", { locale: l }))} />
      </Card>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder>
          <Title order={5} mb="sm">{tx("Change password")}</Title>
          <Stack>
            <PasswordInput label={tx("Current password")} value={current} onChange={(e) => setCurrent(e.currentTarget.value)} />
            <PasswordInput label={tx("New password")} description={tx("At least 8 characters")} value={next} onChange={(e) => setNext(e.currentTarget.value)} />
            <Button onClick={() => changePw.mutate(undefined)} disabled={!current || next.length < 8} loading={changePw.isPending}>{tx("Change password")}</Button>
          </Stack>
        </Card>
        <Card withBorder>
          <Title order={5} mb="xs">{tx("Personal API tokens")}</Title>
          <Text size="sm" c="dimmed" mb="sm">
            {tx("For scripts and integrations: send")} <Code>Authorization: Bearer &lt;token&gt;</Code>{tx(". Tokens act with your permissions.")}
          </Text>
          <Group align="flex-end">
            <TextInput label={tx("Token name")} placeholder={tx("e.g. CI pipeline")} value={tokenName} onChange={(e) => setTokenName(e.currentTarget.value)} style={{ flex: 1 }} />
            <Button onClick={() => createToken.mutate(undefined)} disabled={!tokenName.trim()} loading={createToken.isPending}>{tx("Create")}</Button>
          </Group>
          {created?.token && (
            <Alert color="teal" mt="sm" title={tx("Copy your token now — it will not be shown again")}>
              <Group gap="xs" wrap="nowrap"><Code style={{ overflowWrap: "anywhere" }}>{created.token}</Code>
                <CopyButton value={created.token}>{({ copied, copy }) => <Button size="xs" onClick={copy}>{copied ? tx("Copied") : tx("Copy")}</Button>}</CopyButton>
              </Group>
            </Alert>
          )}
          <Table mt="sm">
            <Table.Tbody>
              {tokens.map((t) => (
                <Table.Tr key={t.id}>
                  <Table.Td><Text size="sm" fw={500}>{t.name}</Text><Text size="xs" c="dimmed" className="mono">{t.prefix}…</Text></Table.Td>
                  <Table.Td><Text size="xs">{tx("created")} {fmtDate(t.created_at)}<br />{tx("last used")} {fmtDateTime(t.last_used_at)}</Text></Table.Td>
                  <Table.Td>{t.revoked_at ? <Badge color="gray">{tx("revoked")}</Badge> :
                    <Button size="xs" variant="subtle" color="red" onClick={() => revoke.mutate(t.id)}>{tx("Revoke")}</Button>}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      </SimpleGrid>
    </>
  );
}
