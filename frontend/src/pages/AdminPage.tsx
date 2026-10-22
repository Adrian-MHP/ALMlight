import { useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, Group, Modal, PasswordInput, Stack, Switch, Table, Text, TextInput } from "@mantine/core";
import { IconPlus, IconShieldCheck } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMe, useProjectMutation, useUsers } from "@/api/hooks";
import type { AdminUser } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { NotFound } from "@/components/NotFound";
import { fmtDateTime } from "@/lib/format";

export function AdminPage() {
  const me = useMe().data!;
  const users = useUsers(me.is_admin).data ?? [];
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [resetFor, setResetFor] = useState<AdminUser | null>(null);
  const [chain, setChain] = useState<{ ok: boolean; checked: number; first_broken_id: number | null } | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });
  const update = useProjectMutation(null, (v: { id: string; patch: Record<string, unknown> }) => api.patch(`/users/${v.id}`, v.patch),
    { success: "User updated", onSuccess: refresh });
  if (!me.is_admin) return <NotFound />;
  return (
    <>
      <PageHeader title="Administration" subtitle="Users and system integrity"
        actions={<Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)} data-testid="new-user">New user</Button>} />
      <Card withBorder mb="lg" p={0}>
        <Table>
          <Table.Thead>
            <Table.Tr><Table.Th>User</Table.Th><Table.Th>E-mail</Table.Th><Table.Th>Last login</Table.Th><Table.Th>Admin</Table.Th><Table.Th>Active</Table.Th><Table.Th /></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {users.map((u) => (
              <Table.Tr key={u.id}>
                <Table.Td><Text size="sm" fw={500}>{u.display_name}</Text><Text size="xs" c="dimmed">{u.username}</Text></Table.Td>
                <Table.Td><Text size="sm">{u.email ?? "–"}</Text></Table.Td>
                <Table.Td><Text size="sm">{fmtDateTime(u.last_login_at)}</Text></Table.Td>
                <Table.Td><Switch checked={u.is_admin} onChange={(e) => update.mutate({ id: u.id, patch: { is_admin: e.currentTarget.checked } })} /></Table.Td>
                <Table.Td><Switch checked={u.is_active} onChange={(e) => update.mutate({ id: u.id, patch: { is_active: e.currentTarget.checked } })} /></Table.Td>
                <Table.Td><Button size="xs" variant="subtle" onClick={() => setResetFor(u)}>Reset password</Button></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
      <Card withBorder>
        <Group justify="space-between">
          <div>
            <Text fw={600}>Audit trail integrity</Text>
            <Text size="sm" c="dimmed">Every change is recorded in a hash-chained audit log. Verify that no entry was altered or removed.</Text>
          </div>
          <Button leftSection={<IconShieldCheck size={16} />} variant="light" data-testid="verify-chain"
            onClick={async () => setChain(await api.get("/admin/audit/verify"))}>Verify</Button>
        </Group>
        {chain && (
          <Alert mt="sm" color={chain.ok ? "green" : "red"}>
            {chain.ok ? `Chain intact — ${chain.checked} entries verified.` : `Chain broken at entry #${chain.first_broken_id} (${chain.checked} checked).`}
          </Alert>
        )}
      </Card>
      <CreateUserModal opened={creating} onClose={() => setCreating(false)} onDone={refresh} />
      <Modal opened={!!resetFor} onClose={() => setResetFor(null)} title={`Reset password — ${resetFor?.username}`}>
        {resetFor && <ResetPassword user={resetFor} onDone={() => setResetFor(null)} />}
      </Modal>
    </>
  );
}

function ResetPassword({ user, onDone }: { user: AdminUser; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const m = useProjectMutation(null, () => api.patch(`/users/${user.id}`, { password }), { success: "Password reset", onSuccess: onDone });
  return (
    <Stack>
      <PasswordInput label="New password" description="At least 8 characters" value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
      <Button onClick={() => m.mutate(undefined)} disabled={password.length < 8} loading={m.isPending}>Set password</Button>
    </Stack>
  );
}

function CreateUserModal({ opened, onClose, onDone }: { opened: boolean; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ username: "", display_name: "", email: "", password: "", is_admin: false });
  const m = useProjectMutation(null, () => api.post("/users", { ...form, email: form.email || null }), {
    success: "User created",
    onSuccess: () => { onDone(); onClose(); setForm({ username: "", display_name: "", email: "", password: "", is_admin: false }); },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="New user">
      <Stack>
        <TextInput label="Username" description="lowercase, e.g. j.doe" required value={form.username}
          onChange={(e) => setForm({ ...form, username: e.currentTarget.value.toLowerCase() })} data-testid="user-username" />
        <TextInput label="Display name" required value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.currentTarget.value })} data-testid="user-display" />
        <TextInput label="E-mail" value={form.email} onChange={(e) => setForm({ ...form, email: e.currentTarget.value })} />
        <PasswordInput label="Initial password" description="At least 8 characters" required value={form.password}
          onChange={(e) => setForm({ ...form, password: e.currentTarget.value })} data-testid="user-password" />
        <Checkbox label={<Group gap={6}>Administrator <Badge size="xs">all projects, users</Badge></Group>} checked={form.is_admin}
          onChange={(e) => setForm({ ...form, is_admin: e.currentTarget.checked })} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button onClick={() => m.mutate(undefined)} loading={m.isPending} data-testid="user-create"
            disabled={!form.username || !form.display_name || form.password.length < 8}>Create</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
