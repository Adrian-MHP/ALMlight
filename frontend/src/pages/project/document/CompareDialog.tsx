import { useState } from "react";
import { Button, Divider, Group, Modal, SegmentedControl, Select, Stack, Text, TextInput } from "@mantine/core";
import { useNavigate } from "react-router-dom";
import { useBaselines, useDocumentHistory, useItems } from "@/api/hooks";
import { fmtDateTime } from "@/lib/format";
import { useProjectCtx } from "../ProjectLayout";
import { tx } from "@/lib/i18n";

type Mode = "live" | "baseline" | "at";

function StatePicker({ label, docKey, mode, setMode, baseline, setBaseline, at, setAt }: {
  label: string; docKey: string; mode: Mode; setMode: (m: Mode) => void; baseline: string | null; setBaseline: (b: string | null) => void;
  at: string | null; setAt: (a: string | null) => void;
}) {
  const { key } = useProjectCtx();
  const baselines = useBaselines(key).data ?? [];
  const history = useDocumentHistory(key, docKey, mode === "at").data;
  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>{label}</Text>
      <SegmentedControl size="xs" value={mode} onChange={(v) => setMode(v as Mode)}
        data={[{ value: "live", label: tx("Live") }, { value: "baseline", label: tx("Baseline") }, { value: "at", label: tx("Point in history") }]} />
      {mode === "baseline" && (
        <Select size="sm" placeholder={tx("Choose a baseline")} value={baseline} onChange={setBaseline}
          data={baselines.map((b) => ({ value: b.id, label: `${b.name}${b.scope ? ` (${b.scope})` : ""}` }))} data-testid={`${label}-baseline`} />
      )}
      {mode === "at" && (
        <Select size="sm" placeholder={tx("Choose a change point")} value={at} onChange={setAt} searchable
          data={(history?.entries ?? []).map((e) => ({ value: e.ts, label: `${fmtDateTime(e.ts)} — ${e.summary.slice(0, 70)}` }))} />
      )}
    </Stack>
  );
}

/** Pick two document states to compare: revisions, baselines, the live state, or another document. */
export function CompareDialog({ docKey, opened, onClose }: { docKey: string; opened: boolean; onClose: () => void }) {
  const { key, model } = useProjectCtx();
  const navigate = useNavigate();
  const [lMode, setLMode] = useState<Mode>("baseline");
  const [lBl, setLBl] = useState<string | null>(null);
  const [lAt, setLAt] = useState<string | null>(null);
  const [rMode, setRMode] = useState<Mode>("live");
  const [rBl, setRBl] = useState<string | null>(null);
  const [rAt, setRAt] = useState<string | null>(null);
  const [rWhich, setRWhich] = useState("same");
  const [rDoc, setRDoc] = useState<string | null>(null);
  const [rProject, setRProject] = useState("");
  const docs = useItems(key, { type: model.documentTypes.map((t) => t.key), limit: 200 }).data?.items ?? [];
  const rightDoc = rWhich === "same" ? docKey : rDoc;
  const ready = (lMode === "live" || (lMode === "baseline" && lBl) || (lMode === "at" && lAt)) &&
    (rMode === "live" || (rMode === "baseline" && rBl) || (rMode === "at" && rAt)) && !!rightDoc;

  function go() {
    const p = new URLSearchParams();
    if (lMode === "baseline" && lBl) p.set("l_bl", lBl);
    if (lMode === "at" && lAt) p.set("l_at", lAt);
    if (rightDoc && rightDoc !== docKey) p.set("r_doc", rightDoc);
    if (rProject.trim()) p.set("r_proj", rProject.trim().toUpperCase());
    if (rMode === "baseline" && rBl) p.set("r_bl", rBl);
    if (rMode === "at" && rAt) p.set("r_at", rAt);
    onClose();
    navigate(`/p/${key}/documents/${docKey}/compare?${p.toString()}`);
  }

  return (
    <Modal opened={opened} onClose={onClose} title={tx("Compare {docKey}", { docKey: docKey })} size="lg">
      <Stack>
        <StatePicker label={tx("Left (older)")} docKey={docKey} mode={lMode} setMode={setLMode} baseline={lBl} setBaseline={setLBl} at={lAt} setAt={setLAt} />
        <Divider />
        <Text size="sm" fw={600}>{tx("Right (newer)")}</Text>
        <SegmentedControl size="xs" value={rWhich} onChange={setRWhich}
          data={[{ value: "same", label: tx("Same document ({docKey})", { docKey: docKey }) }, { value: "other", label: tx("Another document") }]} />
        {rWhich === "other" && (
          <Group grow align="flex-end">
            <Select label={tx("Document")} searchable value={rDoc} onChange={setRDoc} placeholder={tx("Choose…")}
              data={docs.filter((d) => d.key !== docKey).map((d) => ({ value: d.key, label: `${d.key} — ${d.title}` }))} data-testid="compare-other-doc" />
            <TextInput label={tx("…or document key in project")} placeholder={tx("PROJECT (optional)")} value={rProject} onChange={(e) => setRProject(e.currentTarget.value)} />
          </Group>
        )}
        {rWhich === "other" && rProject && <TextInput label={tx("Document key in that project")} value={rDoc ?? ""} onChange={(e) => setRDoc(e.currentTarget.value.toUpperCase())} />}
        <StatePicker label={tx("Right state")} docKey={rightDoc ?? docKey} mode={rMode} setMode={setRMode} baseline={rBl} setBaseline={setRBl} at={rAt} setAt={setRAt} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button onClick={go} disabled={!ready} data-testid="compare-go">{tx("Compare")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
