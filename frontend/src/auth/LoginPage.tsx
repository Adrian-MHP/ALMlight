import { useState } from "react";
import { Alert, Anchor, Box, Button, Center, Group, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconAlertCircle, IconCheck } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "@/api/client";
import { useOidcConfig } from "@/api/hooks";
import { Logo } from "@/components/Logo";
import { PRODUCT } from "@/lib/product";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const sso = useOidcConfig().data;

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
    <div className="login-split">
      <div className="login-brand">
        <Logo size={36} inverted />
        <Title order={2} c="white" mt={48} maw={420} fw={600}>The engineering thread through requirements, documents, variants and change.</Title>
        <Stack gap={10} mt="xl">
          {["Live documents with real-time co-editing", "Full version history, baselines and time travel",
            "Traceability, change control and approvals", "Word, ReqIF and Excel round trips"].map((t) => (
            <Group key={t} gap="xs" wrap="nowrap"><IconCheck size={16} color="var(--mantine-color-petrol-3)" />
              <Text c="gray.3" size="sm">{t}</Text></Group>
          ))}
        </Stack>
        <Text c="gray.6" size="xs" className="login-foot">Runs on your own infrastructure · open REST API</Text>
      </div>
      <Center className="login-form">
        <Box w={360}>
          <Title order={3} mb={4}>Sign in</Title>
          <Text c="dimmed" size="sm" mb="lg">Use your {PRODUCT} account.</Text>
          <Paper withBorder p="lg">
            <form onSubmit={submit}>
              <Stack>
                {error && <Alert color="red" icon={<IconAlertCircle size={16} />}>{error}</Alert>}
                <TextInput label="Username" value={username} onChange={(e) => setUsername(e.currentTarget.value)}
                  autoFocus autoComplete="username" required data-testid="login-username" />
                <PasswordInput label="Password" value={password} onChange={(e) => setPassword(e.currentTarget.value)}
                  autoComplete="current-password" required data-testid="login-password" />
                <Button type="submit" loading={busy} fullWidth data-testid="login-submit">Sign in</Button>
                {sso?.enabled && (
                  <Button variant="default" fullWidth component="a" data-testid="login-sso"
                    href={`/api/v1/auth/oidc/login?next=${encodeURIComponent(params.get("next") ?? "/")}`}>
                    Sign in with {sso.label}
                  </Button>
                )}
              </Stack>
            </form>
          </Paper>
          <Text size="xs" c="dimmed" ta="center" mt="md">
            API documentation: <Anchor href="/api/v1/docs" size="xs">/api/v1/docs</Anchor>
          </Text>
        </Box>
      </Center>
    </div>
  );
}
