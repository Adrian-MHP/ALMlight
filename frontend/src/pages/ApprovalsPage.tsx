import { useState } from "react";
import { SegmentedControl, Stack, Text } from "@mantine/core";
import { useInbox } from "@/api/hooks";
import { ApprovalCard } from "@/components/ApprovalCard";
import { PageHeader } from "@/components/PageHeader";

export function ApprovalsPage() {
  const [status, setStatus] = useState("pending");
  const { data = [], isLoading } = useInbox(status, status === "pending");
  return (
    <>
      <PageHeader title="Approvals" subtitle="Requests waiting for your decision and recent decisions across your projects"
        actions={<SegmentedControl value={status} onChange={setStatus}
          data={[{ value: "pending", label: "Pending" }, { value: "approved", label: "Approved" }, { value: "rejected", label: "Rejected" }]} />} />
      <Stack gap="sm">
        {!isLoading && data.length === 0 && <Text c="dimmed">Nothing here.</Text>}
        {data.map((r) => <ApprovalCard key={r.id} req={r} />)}
      </Stack>
    </>
  );
}
