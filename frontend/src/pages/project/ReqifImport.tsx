import { useState } from "react";
import { Alert, Badge, Button, Card, FileInput, Group, Select, Stack, Table, Text, Title } from "@mantine/core";
import { IconUpload } from "@tabler/icons-react";
import { api } from "@/api/client";
import { useProjectMutation } from "@/api/hooks";
import type { ReqifImportResult } from "@/api/types";
import { useProjectCtx } from "./ProjectLayout";
import { tx } from "@/lib/i18n";

/** Two-step ReqIF import: analyse (dry run with suggested mapping) → adjust mapping → import. */
export function ReqifImport() {
  const { key, model } = useProjectCtx();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ReqifImportResult | null>(null);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [relations, setRelations] = useState<Record<string, string>>({});
  const run = useProjectMutation(key, (dryRun: boolean) => {
    const form = new FormData();
    form.append("file", file!);
    form.append("dry_run", String(dryRun));
    form.append("mapping", JSON.stringify({ types, relations }));
    return api.upload<ReqifImportResult>(`/projects/${key}/import-reqif`, form);
  }, {
    success: (r) => (r.applied ? tx("Imported: {created} created, {updated} updated", { created: r.summary.created, updated: r.summary.updated }) : tx("Analysis complete")),
    onSuccess: (r) => {
      setResult(r);
      setTypes((prev) => ({ ...Object.fromEntries(r.analysis.types.map((t) => [t.name, t.mapped ?? "skip"])), ...prev }));
      setRelations((prev) => ({ ...Object.fromEntries(r.analysis.relations.map((t) => [t.name, t.mapped ?? "skip"])), ...prev }));
    },
  });
  const typeOptions = [{ value: "skip", label: tx("— skip —") }, ...model.config.item_types.map((t) => ({ value: t.key, label: t.label }))];
  const linkOptions = [{ value: "skip", label: tx("— skip —") }, ...model.config.link_types.map((l) => ({ value: l.key, label: l.label }))];
  const unmappedTypes = result?.analysis.types.filter((t) => (types[t.name] ?? "skip") === "skip" && t.count > 0) ?? [];
  return (
    <Card withBorder>
      <Title order={5} mb="xs">{tx("Import ReqIF")}</Title>
      <Text size="xs" c="dimmed" mb="sm">
        {tx("Requirements from customers, suppliers, DOORS or Polarion (.reqif / .reqifz). Object types, attributes and relations are mapped onto this project's information model. Imported objects remember their ReqIF identity, so importing an updated file later updates the items (new versions) instead of duplicating them.")}
      </Text>
      <Stack>
        <FileInput label={tx("ReqIF file")} accept=".reqif,.reqifz,.xml" value={file} leftSection={<IconUpload size={16} />}
          onChange={(f) => { setFile(f); setResult(null); setTypes({}); setRelations({}); }} data-testid="reqif-file" />
        <Group>
          <Button variant="light" disabled={!file} onClick={() => run.mutate(true)} loading={run.isPending && run.variables === true} data-testid="reqif-analyse">
            {result ? tx("Re-check") : tx("Analyse")}
          </Button>
          <Button disabled={!file || !result || result.errors.length > 0} onClick={() => run.mutate(false)}
            loading={run.isPending && run.variables === false} data-testid="reqif-apply">{tx("Import")}</Button>
        </Group>
        {result && (
          <>
            <Alert color={result.errors.length ? "red" : result.applied ? "green" : "blue"} title={result.applied ? tx("Imported") : tx("Analysis of “{title}”", { title: result.title ?? file?.name })}>
              <Group gap={4} mb={4}>{Object.entries(result.summary).map(([k, v]) => <Badge key={k} size="sm" variant="light">{k}: {v}</Badge>)}</Group>
              <Text size="xs">{tx("{objects} objects · {v}", { objects: result.analysis.objects, v: result.analysis.specifications.map((s) => s.name).join(", ") || tx("no specification") })}</Text>
              {result.errors.slice(0, 10).map((e) => <Text key={e} size="xs" c="red">{e}</Text>)}
            </Alert>
            {unmappedTypes.length > 0 && !result.applied && (
              <Alert color="yellow" py={6}>{tx("Choose an item type for {unmappedTypes} — otherwise these objects are skipped. Then re-check.", { unmappedTypes: unmappedTypes.map((t) => `“${t.name}”`).join(", ") })}</Alert>
            )}
            <Table data-testid="reqif-types">
              <Table.Thead><Table.Tr><Table.Th>{tx("ReqIF object type")}</Table.Th><Table.Th ta="right">{tx("Objects")}</Table.Th><Table.Th>{tx("Import as")}</Table.Th><Table.Th>{tx("Attributes")}</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {result.analysis.types.map((t) => (
                  <Table.Tr key={t.name}>
                    <Table.Td><Text size="sm" fw={500}>{t.name}</Text></Table.Td>
                    <Table.Td ta="right">{t.count}</Table.Td>
                    <Table.Td w={220}><Select size="xs" data={typeOptions} value={types[t.name] ?? "skip"} allowDeselect={false}
                      onChange={(v) => setTypes({ ...types, [t.name]: v ?? "skip" })} data-testid={`reqif-map-${t.name}`} /></Table.Td>
                    <Table.Td>
                      <Text size="xs">{tx("title ← {v} · text ← {v1}", { v: t.attributes.title.join(", ") || tx("first line of text"), v1: t.attributes.description.join(", ") || "–" })}</Text>
                      {Object.keys(t.attributes.fields).length > 0 && <Text size="xs">{tx("fields ← {fields}", { fields: Object.entries(t.attributes.fields).map(([a, f]) => `${a} → ${f}`).join(", ") })}</Text>}
                      {t.attributes.unmapped.length > 0 && <Text size="xs" c="dimmed">{tx("not mapped: {unmapped}", { unmapped: t.attributes.unmapped.join(", ") })}</Text>}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            {result.analysis.relations.length > 0 && (
              <Table>
                <Table.Thead><Table.Tr><Table.Th>{tx("ReqIF relation type")}</Table.Th><Table.Th ta="right">{tx("Relations")}</Table.Th><Table.Th>{tx("Import as link")}</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {result.analysis.relations.map((r) => (
                    <Table.Tr key={r.name}>
                      <Table.Td><Text size="sm">{r.name}</Text></Table.Td>
                      <Table.Td ta="right">{r.count}</Table.Td>
                      <Table.Td w={220}><Select size="xs" data={linkOptions} value={relations[r.name] ?? "skip"} allowDeselect={false}
                        onChange={(v) => setRelations({ ...relations, [r.name]: v ?? "skip" })} /></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
            {result.warnings.length > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>{tx("Notes ({length})", { length: result.warnings.length })}</Text>
                {result.warnings.slice(0, 15).map((w) => <Text key={w} size="xs" c="dimmed">{w}</Text>)}
              </Stack>
            )}
          </>
        )}
      </Stack>
    </Card>
  );
}
