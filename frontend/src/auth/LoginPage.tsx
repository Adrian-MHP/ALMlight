import { useState } from "react";
import { Alert, Anchor, Box, Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "@/api/client";
import { Logo } from "@/components/Logo";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const qc = useQueryClient();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api.post("/auth/login", { username, password });
      qc.setQueryData(["me"], me);
      const next = params.get("next");
      navigate(next && next.startsWith("/") && !next.startsWith("//") ? next : "/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Center mih="100vh" bg="var(--mantine-color-default-hover)">
      <Box w={380}>
        <Stack align="center" mb="lg" gap={4}>
          <Logo size={34} />
          <Text c="dimmed" size="sm">Lightweight engineering backbone</Text>
        </Stack>
        <Paper withBorder shadow="sm" p="xl" radius="lg">
          <form onSubmit={submit}>
            <Stack>
              <Title order={4}>Sign in</Title>
              {error && <Alert color="red" icon={<IconAlertCircle size={16} />}>{error}</Alert>}
              <TextInput label="Username" value={username} onChange={(e) => setUsername(e.currentTarget.value)}
                autoFocus autoComplete="username" required data-testid="login-username" />
              <PasswordInput label="Password" value={password} onChange={(e) => setPassword(e.currentTarget.value)}
                autoComplete="current-password" required data-testid="login-password" />
              <Button type="submit" loading={busy} fullWidth data-testid="login-submit">Sign in</Button>
            </Stack>
          </form>
        </Paper>
        <Text size="xs" c="dimmed" ta="center" mt="md">
          API documentation: <Anchor href="/api/v1/docs" size="xs">/api/v1/docs</Anchor>
        </Text>
      </Box>
    </Center>
  );
}
