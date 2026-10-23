import { useState } from "react";
import {
  Alert, Badge, Button, Card, Checkbox, FileInput, Group, Loader, Modal, PasswordInput, Select, SimpleGrid,
  Stack, Table, Text, TextInput, Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconCube, IconDownload, IconFileSpreadsheet, IconGitBranch, IconPlugConnected, IconShieldCheck, IconTransform, IconUpload,
} from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ApiError, downloadUrl } from "@/api/client";
import { pk, useProjectMutation } from "@/api/hooks";
import type { ConnectorResult, ConnectorInfo, Repo, SysmlSettings } from "@/api/types";
import { ItemPicker } from "@/components/ItemPicker";
import { PageHeader } from "@/components/PageHeader";
import { locale, tm, tx } from "@/lib/i18n";
import { useProjectCtx } from "./ProjectLayout";

type Wizard = { system: "ea" | "medini" | "sysml"; kind?: "hara" | "fmea"; title: string };

/** Exchange with tools outside Ariadne: Git, Enterprise Architect, medini analyze, SysML v2 servers, ReqIF. */
export function ConnectorsPage() {
  const { key, can } = useProjectCtx();
  const catalogue = useQuery<ConnectorInfo[]>({ queryKey: ["connectors"], queryFn: () => api.get("/connectors") }).data ?? [];
  const repos = useQuery<Repo[]>({ queryKey: pk(key, "repos"), queryFn: () => api.get(`/projects/${key}/repositories`) }).data ?? [];
  const [wizard, setWizard] = useState<Wizard | null>(null);
  const [writeback, setWriteback] = useState(false);
  const info = (k: string) => catalogue.find((c) => c.key === k);
  const contributor = can("contributor");
  return (
    <>
      <PageHeader title={tx("Connectors")} subtitle={tx("Exchange with the engineering tools around Ariadne — every import is previewed, mapped onto the information model and repeatable")} />
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <ToolCard icon={<IconGitBranch size={22} />} name={tx("Git repositories")} vendor="GitHub · GitLab · Bitbucket · Azure Repos" info={info("git")}
          description={tx("Commits that mention an item key become linked revisions; browse code, diffs and branches.")}>
          <Text size="sm">{repos.length ? tx("{n} repository(ies) connected: {names}", { n: repos.length, names: repos.map((r) => r.name).join(", ") }) : tx("No repository connected yet.")}</Text>
          <Button component={Link} to={`/p/${key}/code`} variant="light" size="xs" data-testid="conn-git">{tx("Open Code page")}</Button>
        </ToolCard>
        <ToolCard icon={<IconCube size={22} />} name="Enterprise Architect" vendor="Sparx Systems" info={info("ea")}
          description={tx("Requirements, blocks, components, activities and their traces from EA models (.qea, XMI). Export as EA XMI or write back into the .qea model.")}>
          <Group gap="xs">
            {contributor && <Button size="xs" leftSection={<IconUpload size={14} />} onClick={() => setWizard({ system: "ea", title: tx("Import from Enterprise Architect") })} data-testid="conn-ea-import">{tx("Import model…")}</Button>}
            <Button size="xs" variant="default" component="a" href={downloadUrl(`/projects/${key}/connectors/ea/export.xmi`)} leftSection={<IconDownload size={14} />} data-testid="conn-ea-export">{tx("Export XMI")}</Button>
            {contributor && <Button size="xs" variant="default" leftSection={<IconTransform size={14} />} onClick={() => setWriteback(true)} data-testid="conn-ea-writeback">{tx("Write back into .qea…")}</Button>}
          </Group>
        </ToolCard>
        <ToolCard icon={<IconShieldCheck size={22} />} name="medini analyze" vendor="Ansys" info={info("medini")}
          description={tx("Hazard analysis (HARA) with ASIL per ISO 26262, FMEA worksheets and safety requirements. Tables go back in the same layout.")}>
          <Group gap="xs">
            {contributor && <Button size="xs" leftSection={<IconUpload size={14} />} onClick={() => setWizard({ system: "medini", kind: "hara", title: tx("Import HARA from medini analyze") })} data-testid="conn-medini-hara">{tx("Import HARA…")}</Button>}
            {contributor && <Button size="xs" leftSection={<IconUpload size={14} />} onClick={() => setWizard({ system: "medini", kind: "fmea", title: tx("Import FMEA from medini analyze") })} data-testid="conn-medini-fmea">{tx("Import FMEA…")}</Button>}
            <Button size="xs" variant="default" component="a" href={downloadUrl(`/projects/${key}/connectors/medini/hara.xlsx`)} leftSection={<IconFileSpreadsheet size={14} />}>{tx("Export HARA")}</Button>
            <Button size="xs" variant="default" component="a" href={downloadUrl(`/projects/${key}/connectors/medini/fmea.xlsx`)} leftSection={<IconFileSpreadsheet size={14} />}>{tx("Export FMEA")}</Button>
          </Group>
          <Text size="xs" c="dimmed">{tx("Safety requirements: ReqIF import and export under Settings → Import / Export (attributes ASIL, Safe state and FTTI map automatically).")}</Text>
        </ToolCard>
        <SysmlCard onImport={() => setWizard({ system: "sysml", title: tx("Import from the SysML v2 server") })} />
        <ToolCard icon={<IconPlugConnected size={22} />} name="ReqIF" vendor="DOORS · Polarion · codebeamer · OEM portals" info={info("reqif")}
          description={tx("Requirements interchange with the mapping wizard; re-imports update the same items.")}>
          <Button component={Link} to={`/p/${key}/settings?tab=io`} variant="light" size="xs">{tx("Open Import / Export")}</Button>
        </ToolCard>
      </SimpleGrid>
      {wizard && <ImportWizard wizard={wizard} onClose={() => setWizard(null)} />}
      {writeback && <WritebackModal onClose={() => setWriteback(false)} />}
    </>
  );
}

function ToolCard({ icon, name, vendor, description, info, children }: {
  icon: React.ReactNode; name: string; vendor: string; description: string; info?: ConnectorInfo; children: React.ReactNode;
}) {
  return (
    <Card withBorder padding="md" data-testid={`tool-${info?.key ?? name}`}>
      <Group gap="sm" mb="xs" wrap="nowrap">
        {icon}
        <div style={{ minWidth: 0 }}>
          <Title order={5}>{name}</Title>
          <Text size="xs" c="dimmed">{vendor}</Text>
        </div>
        <Group gap={4} ml="auto">{info?.formats.slice(0, 4).map((f) => <Badge key={f} size="xs" variant="outline" style={{ textTransform: "none" }}>{f}</Badge>)}</Group>
      </Group>
      <Text size="sm" c="dimmed" mb="sm">{description}</Text>
      <Stack gap="xs">{children}</Stack>
    </Card>
  );
}

function SysmlCard({ onImport }: { onImport: () => void }) {
  const { key, can } = useProjectCtx();
  const qc = useQueryClient();
  const settings = useQuery<SysmlSettings>({ queryKey: pk(key, "sysml"), queryFn: () => api.get(`/projects/${key}/connectors/sysml/settings`) }).data;
  const [base, setBase] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [projects, setProjects] = useState<{ id: string; name: string }[] | null>(null);
  const save = useProjectMutation(key, (v: { project_id?: string | null }) => api.put<SysmlSettings & { projects: { id: string; name: string }[] }>(
    `/projects/${key}/connectors/sysml/settings`, { base_url: base ?? settings?.base_url ?? "", token: token || null, ...v }), {
    success: (r) => r.project_name ? tx("SysML v2 project {name} connected", { name: r.project_name }) : tx("Server reached: {n} project(s)", { n: r.projects.length }),
    onSuccess: (r) => { setProjects(r.projects); setToken(""); qc.invalidateQueries({ queryKey: pk(key, "sysml") }); },
  });
  const url = base ?? settings?.base_url ?? "http://host.docker.internal:8080";
  return (
    <Card withBorder padding="md" data-testid="tool-sysml">
      <Group gap="sm" mb="xs"><IconTransform size={22} /><div><Title order={5}>{tx("SysML v2 API")}</Title><Text size="xs" c="dimmed">SysON · Cameo · Capella</Text></div></Group>
      <Text size="sm" c="dimmed" mb="sm">{tx("Requirement, part, action, interface and verification definitions and usages with satisfy relations from a SysML v2 server (OMG Systems Modeling API).")}</Text>
      {settings?.configured && settings.project_id ? (
        <Group justify="space-between" mb="xs">
          <Text size="sm">{tx("Project {name} on {url}", { name: settings.project_name ?? settings.project_id, url: settings.base_url ?? "" })}</Text>
          {can("contributor") && <Button size="xs" leftSection={<IconUpload size={14} />} onClick={onImport} data-testid="conn-sysml-import">{tx("Import…")}</Button>}
        </Group>
      ) : <Text size="sm" mb="xs">{tx("Not connected yet.")}</Text>}
      {can("manager") && (
        <Stack gap="xs">
          <Group align="flex-end" gap="xs" wrap="wrap">
            <TextInput size="xs" label={tx("Server URL")} value={url} onChange={(e) => setBase(e.currentTarget.value)} style={{ flex: 1, minWidth: 220 }} data-testid="sysml-url" />
            <PasswordInput size="xs" label={tx("Token (optional)")} value={token} onChange={(e) => setToken(e.currentTarget.value)} w={160} />
            <Button size="xs" variant="default" onClick={() => save.mutate({})} loading={save.isPending} data-testid="sysml-connect">{tx("Connect")}</Button>
          </Group>
          {projects && (
            <Select size="xs" label={tx("Project")} data={projects.map((p) => ({ value: p.id, label: p.name }))} value={settings?.project_id ?? null}
              onChange={(v) => v && save.mutate({ project_id: v })} data-testid="sysml-project" placeholder={tx("Choose the model project")} />
          )}
        </Stack>
      )}
    </Card>
  );
}

const SKIP = "skip";

/** Upload (or fetch), analyse, map source kinds onto item and link types, preview, import. */
function ImportWizard({ wizard, onClose }: { wizard: Wizard; onClose: () => void }) {
  const { key, model } = useProjectCtx();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [doc, setDoc] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(false);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [relations, setRelations] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ConnectorResult | null>(null);
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);
  const needsFile = wizard.system !== "sysml";
  const docTypes = model.config.item_types.filter((t) => t.document).map((t) => t.key);
  async function run(dryRun: boolean) {
    setBusy(dryRun ? "preview" : "import");
    try {
      const mapping = { types, relations, ...(doc ? { document: doc } : {}) };
      let r: ConnectorResult;
      if (wizard.system === "sysml") {
        r = await api.post<ConnectorResult>(`/projects/${key}/connectors/sysml/import`, { mapping, dry_run: dryRun, refresh });
      } else {
        const form = new FormData();
        form.append("file", file!);
        form.append("dry_run", dryRun ? "true" : "false");
        form.append("mapping", JSON.stringify(mapping));
        if (wizard.kind) form.append("kind", wizard.kind);
        r = await api.upload<ConnectorResult>(`/projects/${key}/connectors/${wizard.system}/import`, form);
      }
      setResult(r);
      if (!dryRun && r.applied) {
        notifications.show({ color: "teal", message: tx("Imported: {created} created, {updated} updated, {links} links", r.summary) });
        qc.invalidateQueries({ queryKey: pk(key) });
        onClose();
      }
    } catch (e) {
      notifications.show({ color: "red", title: tx("Import failed"), message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }
  const typeOptions = [{ value: SKIP, label: tx("— skip —") }, ...model.config.item_types.map((t) => ({ value: t.key, label: tm(t.label) }))];
  const linkOptions = [{ value: SKIP, label: tx("— skip —") }, ...model.config.link_types.flatMap((l) => [
    { value: l.key, label: tm(l.label) }, { value: `${l.key}:reverse`, label: tx("{label} (reverse)", { label: tm(l.label) }) }])];
  return (
    <Modal opened onClose={onClose} title={wizard.title} size="xl">
      <Stack data-testid="conn-wizard">
        {needsFile && (
          <FileInput label={tx("File")} placeholder={wizard.system === "ea" ? ".qea, .qeax, .xmi" : ".xlsx, .csv"} value={file} clearable
            onChange={(f) => { setFile(f); setResult(null); }} accept={wizard.system === "ea" ? ".qea,.qeax,.xmi,.xml,.eap,.eapx" : ".xlsx,.xlsm,.csv"} data-testid="conn-file" />
        )}
        {wizard.system === "sysml" && <Checkbox label={tx("Read the model again from the server (otherwise a copy of the last hour is used)")} checked={refresh} onChange={(e) => setRefresh(e.currentTarget.checked)} />}
        {wizard.system === "ea" && docTypes.length > 0 && (
          <ItemPicker label={tx("Put new requirements into document (optional)")} types={docTypes} value={doc} onChange={setDoc} w={420} testId="conn-doc"
            description={tx("Headings are created for the EA packages.")} />
        )}
        {result && (
          <>
            <Text fw={600} size="sm">{tx("Element types")}</Text>
            <Table.ScrollContainer minWidth={600}>
              <Table verticalSpacing={4} data-testid="conn-types">
                <Table.Thead><Table.Tr><Table.Th>{tx("In the source")}</Table.Th><Table.Th w={70} ta="right">{tx("Count")}</Table.Th><Table.Th w={240}>{tx("Import as")}</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {result.analysis.types.map((t) => (
                    <Table.Tr key={t.kind}>
                      <Table.Td><Text size="sm" fw={500}>{t.kind}</Text><Text size="xs" c="dimmed" truncate>{t.sample}</Text>
                        {Object.entries(t.attributes).length > 0 && <Text size="xs" c="dimmed">{Object.entries(t.attributes).map(([a, f]) => f ? `${a} → ${f}` : a).join(" · ")}</Text>}</Table.Td>
                      <Table.Td ta="right">{t.count}</Table.Td>
                      <Table.Td><Select size="xs" data={typeOptions} value={types[t.kind] ?? t.mapped ?? SKIP} allowDeselect={false}
                        onChange={(v) => setTypes({ ...types, [t.kind]: v ?? SKIP })} data-testid={`map-type-${t.kind}`} /></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
            {result.analysis.relations.length > 0 && <>
              <Text fw={600} size="sm">{tx("Relations")}</Text>
              <Table verticalSpacing={4} data-testid="conn-relations">
                <Table.Tbody>
                  {result.analysis.relations.map((r) => (
                    <Table.Tr key={r.kind}>
                      <Table.Td><Text size="sm">{r.kind}</Text></Table.Td><Table.Td w={70} ta="right">{r.count}</Table.Td>
                      <Table.Td w={240}><Select size="xs" data={linkOptions} value={relations[r.kind] ?? r.mapped ?? SKIP} allowDeselect={false}
                        onChange={(v) => setRelations({ ...relations, [r.kind]: v ?? SKIP })} /></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </>}
            <Alert color={result.errors.length ? "red" : "blue"} data-testid="conn-preview">
              <Text size="sm" fw={600}>{tx("Preview: {created} new, {updated} updated, {unchanged} unchanged, {links} links", result.summary)}
                {result.summary.conflicts ? tx(", {conflicts} conflict(s)", result.summary) : ""}{result.summary.frozen ? tx(", {frozen} frozen", result.summary) : ""}</Text>
              {[...result.errors, ...result.warnings].slice(0, 12).map((w, i) => <Text key={i} size="xs">{w}</Text>)}
            </Alert>
          </>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button variant={result ? "default" : "filled"} onClick={() => run(true)} disabled={needsFile && !file} loading={busy === "preview"} data-testid="conn-preview-run">{result ? tx("Preview again") : tx("Analyse")}</Button>
          <Button onClick={() => run(false)} disabled={!result || result.errors.length > 0} loading={busy === "import"} data-testid="conn-apply">{tx("Import")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function WritebackModal({ onClose }: { onClose: () => void }) {
  const { key } = useProjectCtx();
  const [file, setFile] = useState<File | null>(null);
  const [packages, setPackages] = useState<{ id: string; name: string; path: string }[] | null>(null);
  const [pkg, setPkg] = useState<string | null>(null);
  const [ql, setQl] = useState("");
  const [busy, setBusy] = useState(false);
  async function load(f: File | null) {
    setFile(f);
    setPackages(null);
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    form.append("dry_run", "true");
    try {
      const r = await api.upload<ConnectorResult>(`/projects/${key}/connectors/ea/import`, form);
      setPackages(r.analysis.packages);
    } catch (e) {
      notifications.show({ color: "red", message: e instanceof ApiError ? e.message : String(e) });
    }
  }
  async function write() {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file!);
      form.append("package", pkg!);
      if (ql.trim()) form.append("ql", ql.trim());
      const res = await fetch(`/api/v1/projects/${key}/connectors/ea/writeback`, { method: "POST", body: form, credentials: "same-origin", headers: { "Accept-Language": locale() } });
      if (!res.ok) throw new Error((await res.json()).error?.message ?? res.statusText);
      const counts = JSON.parse(res.headers.get("X-Ariadne-Counts") ?? "{}");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = file!.name.replace(/\.(qea|qeax)$/i, "") + "-ariadne.qea";
      a.click();
      notifications.show({ color: "teal", message: tx("Model written: {created} created, {updated} updated, {connectors} connectors", counts) });
      onClose();
    } catch (e) {
      notifications.show({ color: "red", message: String((e as Error).message) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal opened onClose={onClose} title={tx("Write back into an Enterprise Architect model")} size="lg">
      <Stack data-testid="conn-writeback">
        <Text size="sm" c="dimmed">{tx("Ariadne writes into a copy of your .qea model: elements it knows by GUID are updated, new items are created in the chosen package, traces become connectors. Open the downloaded file in EA.")}</Text>
        <FileInput label={tx("EA model (.qea / .qeax)")} value={file} onChange={load} accept=".qea,.qeax" data-testid="wb-file" />
        {file && !packages && <Loader size="sm" />}
        {packages && <Select label={tx("Package for new elements")} searchable data={packages.map((p) => ({ value: p.id, label: p.path }))} value={pkg} onChange={setPkg} data-testid="wb-package" />}
        <TextInput label={tx("Which items (query, optional)")} placeholder="type:system_requirement" value={ql} onChange={(e) => setQl(e.currentTarget.value)}
          description={tx("Empty: all requirements, elements, functions, interfaces and tests")} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{tx("Cancel")}</Button>
          <Button onClick={write} disabled={!file || !pkg} loading={busy} data-testid="wb-run">{tx("Write and download")}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
