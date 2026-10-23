import { ActionIcon, Badge, Button, Group, Indicator, Popover, ScrollArea, Stack, Text, ThemeIcon, Tooltip, UnstyledButton } from "@mantine/core";
import { IconAt, IconBell, IconChecks, IconEye, IconListDetails, IconSignature, IconUser } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useNotifications } from "@/api/hooks";
import type { AppNotification } from "@/api/types";
import { fmtRelative } from "@/lib/format";

const KIND = {
  mention: { icon: IconAt, color: "violet", label: "mentioned you" },
  approval: { icon: IconSignature, color: "orange", label: "approval" },
  owner: { icon: IconUser, color: "blue", label: "your item" },
  watch: { icon: IconEye, color: "teal", label: "watched" },
  digest: { icon: IconListDetails, color: "gray", label: "summary" },
} as const;

/** Bell in the header: notifications from watched items, own items, approvals and mentions. */
export function NotificationCenter() {
  const [opened, setOpened] = useState(false);
  const { data } = useNotifications();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const unread = data?.unread ?? 0;
  async function read(ids: string[] | "all") {
    await api.post("/notifications/read", ids === "all" ? { all: true } : { ids });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  }
  function open(n: AppNotification) {
    if (!n.read) read([n.id]);
    setOpened(false);
    if (n.project && n.item_key) navigate(`/p/${n.project}/items/${n.item_key}`);
    else if (n.kind === "approval") navigate("/approvals");
  }
  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-end" width={400} shadow="lg" offset={8}>
      <Popover.Target>
        <Tooltip label="Notifications" disabled={opened}>
          <Indicator disabled={unread === 0} label={unread > 99 ? "99+" : unread} size={16} color="red" offset={4}>
            <ActionIcon variant="subtle" color="gray" size="lg" className="header-icon" onClick={() => setOpened((o) => !o)}
              aria-label="Notifications" data-testid="notifications">
              <IconBell size={20} />
            </ActionIcon>
          </Indicator>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p={0} data-testid="notification-center">
        <Group justify="space-between" px="md" py="xs" style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}>
          <Text fw={600}>Notifications {unread > 0 && <Badge size="sm" color="red" ml={4}>{unread}</Badge>}</Text>
          <Group gap={4}>
            <Button size="compact-xs" variant="subtle" leftSection={<IconChecks size={14} />} disabled={!unread} onClick={() => read("all")}
              data-testid="notifications-read-all">Mark all read</Button>
          </Group>
        </Group>
        <ScrollArea.Autosize mah={440}>
          <Stack gap={0}>
            {(data?.items ?? []).map((n) => {
              const k = KIND[n.kind] ?? KIND.watch;
              return (
                <UnstyledButton key={n.id} onClick={() => open(n)} className={`note-row${n.read ? "" : " is-unread"}`} data-testid={`note-${n.kind}`}>
                  <Group gap="sm" wrap="nowrap" align="flex-start">
                    <ThemeIcon size={28} radius="xl" variant="light" color={k.color}><k.icon size={15} /></ThemeIcon>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <Text size="sm" lineClamp={2}>{n.title}</Text>
                      <Text size="xs" c="dimmed">{n.actor ? `${n.actor} · ` : ""}{k.label}{n.project ? ` · ${n.project}` : ""} · {fmtRelative(n.created_at)}</Text>
                      {n.body && n.kind !== "digest" && <Text size="xs" c="dimmed" lineClamp={2} mt={2}>{n.body}</Text>}
                    </div>
                    {!n.read && <span className="note-dot" />}
                  </Group>
                </UnstyledButton>
              );
            })}
            {(data?.items ?? []).length === 0 && <Text c="dimmed" size="sm" p="md">Nothing yet. Watch items or documents to follow changes; mentions and approvals arrive here too.</Text>}
          </Stack>
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  );
}
