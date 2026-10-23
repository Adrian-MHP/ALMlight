import { useMemo, useState } from "react";
import { Alert, Badge, Button, Group, Modal, PasswordInput, ScrollArea, Select, Stack, Table, Text, Textarea } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import { pk, useDirectory, useItems } from "@/api/hooks";
import type { BulkResult, FieldDef, QNode } from "@/api/types";
import { FieldsForm } from "@/components/FieldsForm";
import { ItemPicker } from "@/components/ItemPicker";
import type { Model } from "@/lib/model";
import { tx } from "@/lib/i18n";

export type BulkAction = "update" | "transition" | "plan" | "unplan" | "link" | "watch" | "unwatch" | "delete";

export interface BulkSelection {
  keys?: string[];
  query?: { q?: string; conditions?: QNode[] };
  /** types of the selected items (for offering fields, transitions and links) */
  types: string[];
  count: number;
}

const TITLES: Record<BulkAction, string> = {
  update: tx("Edit fields"), transition: tx("Change status"), plan: tx("Plan into a release"), unplan: tx("Remove from a release"),
  link: tx("Add a link"), watch: tx("Watch"), unwatch: tx("Stop watching"), delete: tx("Move to the recycle bin"),
};
const STATUS_COLOR = { ok: "teal", unchanged: "gray", skipped: "orange" } as const;

/** Configure a bulk action, preview it (dry run, per-item result) and apply it. */
export function BulkModal({ projectKey, model, action, selection, onClose, onDone }: {
  projectKey: string; model: Model; action: BulkAction | null; selection: BulkSelection; onClose: () => void; onDone?: () => void;
}) {
  const qc = useQueryClient();
  const users = useDirectory().data ?? [];
  const [fieldKey, setFieldKey] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [owner, setOwner] = useState<string | null>(null);
  const [transition, setTransition] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [password, setPassword] = useState("");
  const [release, setRelease] = useState<string | null>(null);
  const [fromRelease, setFromRelease] = useState<string | null>(null);
  const [linkOption, setLinkOption] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [preview, setPreview] = useState<BulkResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const releases = useItems(projectKey, { type: model.releaseType ? [model.releaseType.key] : [], limit: 200 }, !!model.releaseType && (action === "plan" || action === "unplan")).data?.items ?? [];
  const types = selection.types.length ? selection.types : model.config.item_types.map((t) => t.key);

  const fieldOptions = useMemo(() => {
    const map = new Map<string, FieldDef>();
    for (const t of types) for (const f of model.type(t)?.fields ?? []) if (!f.formula && !f.classify && f.type !== "steps" && !map.has(f.key)) map.set(f.key, f);
    return [{ value: "__owner", label: tx("Owner") }, ...[...map.values()].map((f) => ({ value: f.key, label: f.label }))];
  }, [model, types]);
  const fieldDef = fieldKey && fieldKey !== "__owner"
    ? types.map((t) => model.field(t, fieldKey)).find(Boolean) : undefined;
  const transitions = useMemo(() => {
    const map = new Map<string, { label: string; signature: boolean; comment: boolean; approval: boolean }>();
    for (const t of types) {
      for (const tr of model.workflow(t)?.transitions ?? []) {
        if (!map.has(tr.key)) map.set(tr.key, { label: tr.label, signature: !!tr.signature, comment: !!tr.comment_required, approval: !!tr.approval });
      }
    }
    return map;
  }, [model, types]);
  const tr = transition ? transitions.get(transition) : undefined;
  const linkOptions = useMemo(() => {
    const first = types[0];
    if (!first) return [];
    return model.linkOptions(first).filter((o) => types.every((t) => model.linkOptions(t).some((x) => x.value === o.value)));
  }, [model, types]);
  const link = linkOptions.find((o) => o.value === linkOption);

  function body(dryRun: boolean): Record<string, unknown> {
    const sel = selection.keys ? { keys: selection.keys } : { query: selection.query };
    const b: Record<string, unknown> = { ...sel, action, dry_run: dryRun };
    if (action === "update") {
      if (fieldKey === "__owner") { b.owner_id = owner; b.set_owner = true; } else if (fieldKey) b.fields = { [fieldKey]: values[fieldKey] ?? null };
    }
    if (action === "transition") Object.assign(b, { transition, comment: comment || null, password: password || null });
    if (action === "plan" || action === "unplan") Object.assign(b, { release, from_release: fromRelease });
    if (action === "link" && link) Object.assign(b, { link_type: link.linkType, link_dir: link.direction === "outgoing" ? "out" : "in", target });
    return b;
  }
  const ready = action === "update" ? !!fieldKey : action === "transition" ? !!transition && (!tr?.comment || !!comment.trim())
    : action === "plan" || action === "unplan" ? !!release : action === "link" ? !!link && !!target : true;

  async function run(dryRun: boolean) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<BulkResult>(`/projects/${projectKey}/items/bulk`, body(dryRun));
      if (dryRun) setPreview(res);
      else {
        const ok = res.summary.ok ?? 0;
        notifications.show({ color: ok ? "teal" : "orange", message: tx("{v}: {ok} changed{v1}{v2}", { v: TITLES[action!], ok: ok, v1: res.summary.skipped ? tx(", {skipped} skipped", { skipped: res.summary.skipped }) : "", v2: res.summary.unchanged ? tx(", {unchanged} unchanged", { unchanged: res.summary.unchanged }) : "" }) });
        qc.invalidateQueries({ queryKey: pk(projectKey) });
        qc.invalidateQueries({ queryKey: ["subscriptions"] });
        onDone?.();
        close();
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function close() {
    setPreview(null); setError(null); setFieldKey(null); setValues({}); setTransition(null); setComment(""); setPassword("");
    setRelease(null); setFromRelease(null); setLinkOption(null); setTarget(null);
    onClose();
  }
  const releaseOptions = releases.map((r) => ({ value: r.key, label: `${r.key} — ${r.title}` }));
  return (
    <Modal opened={!!action} onClose={close} size="lg" title={action ? tx("{v} — {count} item(s)", { v: TITLES[action], count: selection.count }) : ""}>
      <Stack data-testid="bulk-modal">
        {action === "update" && (
          <>
            <Select label={tx("Field")} placeholder={tx("Choose a field")} data={fieldOptions} value={fieldKey} searchable
              onChange={(v) => { setFieldKey(v); setPreview(null); }} data-testid="bulk-field" />
            {fieldKey === "__owner" && <Select label={tx("New owner")} clearable placeholder={tx("Nobody")} data={users.map((u) => ({ value: u.id, label: u.display_name }))}
              value={owner} onChange={(v) => { setOwner(v); setPreview(null); }} data-testid="bulk-owner" />}
            {fieldDef && <FieldsForm defs={[fieldDef]} values={values} onChange={(k, v) => { setValues({ ...values, [k]: v }); setPreview(null); }} />}
            {fieldDef && <Text size="xs" c="dimmed">{tx("An empty value clears the field. Items whose type has no such field and frozen items are skipped.")}</Text>}
          </>
        )}
        {action === "transition" && (
          <>
            <Select label={tx("Transition")} placeholder={tx("Choose")} data={[...transitions].map(([value, t]) => ({ value, label: `${t.label}${t.approval ? " (approval)" : ""}` }))}
              value={transition} onChange={(v) => { setTransition(v); setPreview(null); }} data-testid="bulk-transition" />
            {tr && (tr.comment || tr.approval) && <Textarea label={tx("Comment{v}", { v: tr.comment ? tx(" (required)") : "" })} value={comment} onChange={(e) => setComment(e.currentTarget.value)} />}
            {tr?.signature && <PasswordInput label={tx("Electronic signature — your password")} description={tx("Signed once for all items")} value={password} onChange={(e) => setPassword(e.currentTarget.value)} />}
            <Text size="xs" c="dimmed">{tx("Items not in a state where the transition is possible are skipped. Approval transitions request an approval per item.")}</Text>
          </>
        )}
        {(action === "plan" || action === "unplan") && (
          <>
            <Select label={action === "plan" ? tx("Release, iteration or milestone") : tx("Remove from")} data={releaseOptions} value={release} searchable
              onChange={(v) => { setRelease(v); setPreview(null); }} data-testid="bulk-release" />
            {action === "plan" && <Select label={tx("Move from (optional)")} description={tx("Remove the items from this plan at the same time")} clearable data={releaseOptions}
              value={fromRelease} onChange={(v) => { setFromRelease(v); setPreview(null); }} />}
          </>
        )}
        {action === "link" && (
          <>
            <Select label={tx("Link")} placeholder={linkOptions.length ? tx("Choose") : tx("No link type fits all selected types")} data={linkOptions.map((o) => ({ value: o.value, label: o.label }))}
              value={linkOption} onChange={(v) => { setLinkOption(v); setTarget(null); setPreview(null); }} data-testid="bulk-link" />
            {link && <ItemPicker label={tx("Item")} types={link.otherTypes} value={target} onChange={(v) => { setTarget(v); setPreview(null); }} testId="bulk-target" />}
          </>
        )}
        {action === "delete" && <Alert color="red">{tx("Deleted items go to the recycle bin with their links and can be restored by a manager. Released items cannot be deleted and are skipped.")}</Alert>}
        {error && <Alert color="red" data-testid="bulk-error">{error}</Alert>}
        {preview && (
          <div data-testid="bulk-preview">
            <Group gap={6} mb={6}>
              <Text size="sm" fw={600}>{tx("Preview")}</Text>
              {Object.entries(preview.summary).map(([k, n]) => <Badge key={k} color={STATUS_COLOR[k as keyof typeof STATUS_COLOR] ?? "gray"} variant="light">{k}: {n}</Badge>)}
            </Group>
            <ScrollArea.Autosize mah={260}>
              <Table verticalSpacing={4} fz="sm">
                <Table.Tbody>
                  {preview.results.map((r) => (
                    <Table.Tr key={r.key}>
                      <Table.Td w={90}><Text className="item-key" size="xs">{r.key}</Text></Table.Td>
                      <Table.Td><Text size="xs" lineClamp={1}>{r.title}</Text></Table.Td>
                      <Table.Td w={90}><Badge size="xs" variant="light" color={STATUS_COLOR[r.status]}>{r.status}</Badge></Table.Td>
                      <Table.Td><Text size="xs" c="dimmed">{r.message}</Text></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea.Autosize>
          </div>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>{tx("Cancel")}</Button>
          <Button variant="light" onClick={() => run(true)} disabled={!ready} loading={busy && !preview} data-testid="bulk-preview-run">{tx("Preview")}</Button>
          <Button color={action === "delete" ? "red" : undefined} onClick={() => run(false)} disabled={!ready || !preview || !(preview.summary.ok)}
            loading={busy && !!preview} data-testid="bulk-apply">{tx("Apply to {ok} item(s)", { ok: preview?.summary.ok ?? 0 })}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
