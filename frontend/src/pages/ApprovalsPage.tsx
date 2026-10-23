import { useState } from "react";
import { SegmentedControl, Stack, Text } from "@mantine/core";
import { useInbox } from "@/api/hooks";
import { ApprovalCard } from "@/components/ApprovalCard";
import { PageHeader } from "@/components/PageHeader";
import { tx } from "@/lib/i18n";

export function ApprovalsPage() {
  const [status, setStatus] = useState("pending");
  const { data = [], isLoading } = useInbox(status, status === "pending");
  return (
    <>
      <PageHeader title={tx("Approvals")} subtitle={tx("Requests waiting for your decision and recent decisions across your projects")}
        actions={<SegmentedControl value={status} onChange={setStatus}
          data={[{ value: "pending", label: tx("Pending") }, { value: "approved", label: tx("Approved") }, { value: "rejected", label: tx("Rejected") }]} />} />
      <Stack gap="sm">
        {!isLoading && data.length === 0 && <Text c="dimmed">{tx("Nothing here.")}</Text>}
        {data.map((r) => <ApprovalCard key={r.id} req={r} />)}
      </Stack>
    </>
  );
}
