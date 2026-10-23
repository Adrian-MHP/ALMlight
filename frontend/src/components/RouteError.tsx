import { Alert, Button, Code, Group, Stack, Text } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useRouteError } from "react-router-dom";
import { tx } from "@/lib/i18n";

/** Shown inside the app shell when a page fails to render — the navigation keeps working. */
export function RouteError() {
  const error = useRouteError() as { message?: string; statusText?: string } | undefined;
  const message = error?.message ?? error?.statusText ?? String(error);
  return (
    <Alert color="red" icon={<IconAlertTriangle size={18} />} title={tx("This page could not be displayed")} data-testid="route-error" mt="md">
      <Stack gap="xs">
        <Text size="sm">{tx("Something went wrong while showing this page. Your data is not affected. Reload the page or go back; if it happens again, send the message below to your administrator.")}</Text>
        <Code block>{message}</Code>
        <Group><Button size="xs" onClick={() => window.location.reload()}>{tx("Reload")}</Button><Button size="xs" variant="default" onClick={() => window.history.back()}>{tx("Back")}</Button></Group>
      </Stack>
    </Alert>
  );
}
