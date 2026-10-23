import { Badge, Group, Text, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconCircleCheck, IconCircleDashed, IconCircleHalf2, IconCircleX, IconLock, IconRefresh } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import type { Item, VerificationStatus } from "@/api/types";
import { CATEGORY_COLORS, stateColor } from "@/lib/model";
import { useProjectCtx } from "@/pages/project/ProjectLayout";
import { tm, tx } from "@/lib/i18n";

export function StateBadge({ item, size = "sm" }: { item: Pick<Item, "lifecycle">; size?: "xs" | "sm" | "md" }) {
  const lc = item.lifecycle;
  if (!lc.state) return null;
  return (
    <Badge size={size} variant="light" color={stateColor(lc.color, lc.category)}
      leftSection={lc.frozen ? <IconLock size={10} /> : undefined}>
      {tm(lc.label) ?? lc.state}
    </Badge>
  );
}

export function StateKeyBadge({ typeKey, state }: { typeKey: string; state: string | null }) {
  const { model } = useProjectCtx();
  const s = model.state(typeKey, state);
  if (!state) return null;
  return <Badge size="sm" variant="light" color={stateColor(s?.color, s?.category)}>{s?.label ?? state}</Badge>;
}

export function TypeBadge({ typeKey }: { typeKey: string }) {
  const { model } = useProjectCtx();
  const t = model.type(typeKey);
  return (
    <Badge size="sm" variant="outline" color={t?.color ?? CATEGORY_COLORS[t?.category ?? "other"]} style={{ textTransform: "none" }}>
      {t?.label ?? typeKey}
    </Badge>
  );
}

export function ItemLink({ item, withTitle = false }: { item: { key: string; title?: string; project_key?: string }; withTitle?: boolean }) {
  const { key: projectKey } = useProjectCtx();
  const p = item.project_key ?? projectKey;
  return (
    <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
      <Link to={`/p/${p}/items/${item.key}`} className="item-key" style={{ color: "var(--mantine-color-anchor)" }}>
        {p !== projectKey ? `${p}:` : ""}{item.key}
      </Link>
      {withTitle && item.title && <Text size="sm" truncate>{item.title}</Text>}
    </Group>
  );
}

const VERIFICATION: Record<VerificationStatus, { color: string; label: string; icon: typeof IconCircleCheck }> = {
  passed: { color: "green", label: tx("Verified"), icon: IconCircleCheck },
  failed: { color: "red", label: tx("Failed"), icon: IconCircleX },
  retest: { color: "orange", label: tx("Re-test"), icon: IconRefresh },
  not_run: { color: "gray", label: tx("Not run"), icon: IconCircleDashed },
  none: { color: "gray", label: tx("No tests"), icon: IconCircleDashed },
};

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  const v = VERIFICATION[status];
  return (
    <Badge size="sm" variant={status === "none" ? "outline" : "light"} color={v.color} leftSection={<v.icon size={11} />}>
      {v.label}
    </Badge>
  );
}

export function MaturityDot({ value, label }: { value: "done" | "partial" | "none"; label: string }) {
  const color = value === "done" ? "var(--mantine-color-green-6)" : value === "partial" ? "var(--mantine-color-yellow-6)" : "var(--mantine-color-gray-4)";
  const Icon = value === "done" ? IconCircleCheck : value === "partial" ? IconCircleHalf2 : IconCircleDashed;
  return (
    <Tooltip label={`${label}: ${value}`}>
      <Icon size={18} color={color} />
    </Tooltip>
  );
}

export function SuspectBadge({ reason }: { reason?: string | null }) {
  return (
    <Tooltip label={reason ?? tx("The linked item changed — review this link")}>
      <Badge size="sm" color="orange" variant="light" leftSection={<IconAlertTriangle size={11} />}>{tx("suspect")}</Badge>
    </Tooltip>
  );
}
