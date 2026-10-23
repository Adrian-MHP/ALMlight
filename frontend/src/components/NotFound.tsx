import { Button, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router-dom";
import { tx } from "@/lib/i18n";

export function NotFound({ message }: { message?: string }) {
  return (
    <Stack align="center" mt={80} gap="sm">
      <Title order={3}>{tx("Not found")}</Title>
      <Text c="dimmed">{message ?? tx("This page does not exist or you have no access to it.")}</Text>
      <Button component={Link} to="/" variant="light">{tx("Back to projects")}</Button>
    </Stack>
  );
}
