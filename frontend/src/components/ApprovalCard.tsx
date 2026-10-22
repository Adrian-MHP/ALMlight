import { useState } from "react";
import { Badge, Button, Card, Group, Stack, Text } from "@mantine/core";
import { IconCheck, IconX } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { useProjectMutation } from "@/api/hooks";
import type { ApprovalRequest } from "@/api/types";
import { fmtDateTime } from "@/lib/format";
import { ActionPrompt } from "./PasswordPrompt";

/** One approval request with its votes and approve / reject actions for eligible users. */
export function ApprovalCard({ req, showItem = true }: { req: ApprovalRequest; showItem?: boolean }) {
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const vote = useProjectMutation(req.project_key, (v: { decision: string; comment: string; password: string }) =>
    api.post(`/projects/${req.project_key}/approvals/${req.id}/vote`, v), {
    success: (r) => `Vote recorded (${(r as { status: string }).status})`,
    onSuccess: () => setDecision(null),
  });
  const cancel = useProjectMutation(req.project_key, () => api.post(`/projects/${req.project_key}/approvals/${req.id}/cancel`),
    { success: "Request withdrawn" });
  const approvals = req.votes.filter((v) => v.decision === "approve").length;
  const statusColor = { pending: "yellow", approved: "green", rejected: "red", cancelled: "gray" }[req.status];
  return (
    <Card withBorder padding="sm" data-testid={`approval-${req.item_key}`}>
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Stack gap={4} style={{ minWidth: 0 }}>
          <Group gap="xs">
            <Badge color={statusColor} variant="light">{req.status}</Badge>
            <Text fw={600} size="sm">{req.label}</Text>
            {showItem && (
              <Text size="sm" truncate>
                <Link to={`/p/${req.project_key}/items/${req.item_key}`} className="item-key">{req.project_key}/{req.item_key}</Link>{" "}
                {req.item_title}
              </Text>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            {req.from_state} → {req.to_state} · version {req.version_no} · requested by {req.requested_by?.display_name} on {fmtDateTime(req.created_at)}
            · {approvals}/{req.required} approvals by {req.roles.join("/")}{req.signature_required ? " · e-signature" : ""}
          </Text>
          {req.comment && <Text size="sm">“{req.comment}”</Text>}
          {req.votes.map((v, i) => (
            <Text key={i} size="xs">
              {v.decision === "approve" ? "✔" : "✘"} {v.user?.display_name} — {v.meaning}{v.signed ? " (signed)" : ""}
              {v.comment ? `: ${v.comment}` : ""} · {fmtDateTime(v.at)}
            </Text>
          ))}
          {req.status === "pending" && !req.can_vote && req.cannot_vote_reason && (
            <Text size="xs" c="dimmed">You cannot vote: {req.cannot_vote_reason}</Text>
          )}
        </Stack>
        {req.status === "pending" && (
          <Group gap="xs" wrap="nowrap">
            {req.can_vote && (
              <>
                <Button size="xs" color="green" leftSection={<IconCheck size={14} />} onClick={() => setDecision("approve")} data-testid="vote-approve">Approve</Button>
                <Button size="xs" color="red" variant="light" leftSection={<IconX size={14} />} onClick={() => setDecision("reject")} data-testid="vote-reject">Reject</Button>
              </>
            )}
            <Button size="xs" variant="subtle" color="gray" onClick={() => cancel.mutate(undefined)}>Withdraw</Button>
          </Group>
        )}
      </Group>
      {decision && (
        <ActionPrompt opened onClose={() => setDecision(null)} title={decision === "approve" ? "Approve" : "Reject"}
          meaning={`${decision === "approve" ? "Approve" : "Reject"}: ${req.label} of ${req.item_key} (version ${req.version_no})`}
          signature={req.signature_required} commentRequired={decision === "reject"} color={decision === "approve" ? "green" : "red"}
          confirmLabel={decision === "approve" ? "Approve" : "Reject"} loading={vote.isPending}
          onConfirm={(r) => vote.mutate({ decision, comment: r.comment, password: r.password })} />
      )}
    </Card>
  );
}
