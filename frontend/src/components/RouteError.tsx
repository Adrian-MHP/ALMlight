import { Alert, Button, Code, Group, Stack, Text } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useRouteError } from "react-router-dom";

/** Shown inside the app shell when a page fails to render — the navigation keeps working. */
export function RouteError() {
  const error = useRouteError() as { message?: string; statusText?: string } | undefined;
  const message = error?.message ?? error?.statusText ?? String(error);
  return (
    <Alert color="red" icon={<IconAlertTriangle size={18} />} title="This page could not be displayed" data-testid="route-error" mt="md">
      <Stack gap="xs">
        <Text size="sm">Something went wrong while showing this page. Your data is not affected. Reload the page or go back; if it happens again, send the message below to your administrator.</Text>
        <Code block>{message}</Code>
        <Group><Button size="xs" onClick={() => window.location.reload()}>Reload</Button><Button size="xs" variant="default" onClick={() => window.history.back()}>Back</Button></Group>
      </Stack>
    </Alert>
  );
}
