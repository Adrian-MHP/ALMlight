import { Button, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router-dom";

export function NotFound({ message }: { message?: string }) {
  return (
    <Stack align="center" mt={80} gap="sm">
      <Title order={3}>Not found</Title>
      <Text c="dimmed">{message ?? "This page does not exist or you have no access to it."}</Text>
      <Button component={Link} to="/" variant="light">Back to projects</Button>
    </Stack>
  );
}
