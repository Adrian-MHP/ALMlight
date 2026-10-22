import type { ReactNode } from "react";
import { Group, Stack, Text, Title } from "@mantine/core";

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <Group justify="space-between" align="flex-start" mb="md" wrap="wrap" gap="sm">
      <Stack gap={2}>
        <Title order={2} size="h3">{title}</Title>
        {subtitle && <Text c="dimmed" size="sm">{subtitle}</Text>}
      </Stack>
      {actions && <Group gap="xs">{actions}</Group>}
    </Group>
  );
}
