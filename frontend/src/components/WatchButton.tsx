import { Button, Tooltip } from "@mantine/core";
import { IconEye, IconEyeCheck } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { pk, useWatch } from "@/api/hooks";
import { tx } from "@/lib/i18n";

/** Watch an item or document: notifications about every change (documents: including their content). */
export function WatchButton({ projectKey, itemKey, size = "sm", document = false }: {
  projectKey: string; itemKey: string; size?: "xs" | "sm"; document?: boolean;
}) {
  const qc = useQueryClient();
  const { data } = useWatch(projectKey, itemKey);
  const watching = !!data?.watching;
  async function toggle() {
    const path = `/projects/${projectKey}/items/${itemKey}/watch`;
    const res = watching ? await api.del(path) : await api.put(path, {});
    qc.setQueryData(pk(projectKey, "item", itemKey, "watch"), res);
  }
  return (
    <Tooltip label={watching ? tx("You get notifications about changes — click to stop") : tx("Get notified about every change{v}", { v: document ? tx(" in this document") : "" })}>
      <Button size={size} variant={watching ? "light" : "default"} onClick={toggle} data-testid="watch-toggle"
        leftSection={watching ? <IconEyeCheck size={16} /> : <IconEye size={16} />}>
        {watching ? tx("Watching") : tx("Watch")}{data?.watchers ? ` · ${data.watchers}` : ""}
      </Button>
    </Tooltip>
  );
}
