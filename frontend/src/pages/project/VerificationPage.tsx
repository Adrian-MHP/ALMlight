import { useState } from "react";
import { Alert, Badge, Button, Card, FileInput, Group, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput } from "@mantine/core";
import { IconPlus, IconUpload } from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useFeatureModel, useItems, useMaturity, useProjectMutation } from "@/api/hooks";
import { ItemLink, MaturityDot, StateBadge } from "@/components/badges";
import { PageHeader } from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";
import { ItemFormModal } from "./ItemFormModal";
import { useProjectCtx } from "./ProjectLayout";

export function VerificationPage() {
  const { model } = useProjectCtx();
  const runType = model.config.semantics.test_run_type;
  return (
    <>
      <PageHeader title="Verification" subtitle="Test runs, CI results and the maturity of every system element" />
      <Tabs defaultValue="runs">
        <Tabs.List mb="md">
          <Tabs.Tab value="runs">Test runs</Tabs.Tab>
          <Tabs.Tab value="maturity" data-testid="tab-maturity">Maturity</Tabs.Tab>
          <Tabs.Tab value="ci">CI import</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="runs">{runType && model.type(runType) ? <Runs runType={runType} /> : <Text c="dimmed">No test run type configured.</Text>}</Tabs.Panel>
        <Tabs.Panel value="maturity"><Maturity /></Tabs.Panel>
        <Tabs.Panel value="ci"><CiImport /></Tabs.Panel>
      </Tabs>
    </>
  );
}

function Runs({ runType }: { runType: string }) {
  const { key, can } = useProjectCtx();
  const { data } = useItems(key, { type: [runType], limit: 200, sort: "-updated" });
  const [creating, setCreating] = useState(false);
  return (
    <>
      {can("contributor") && <Button leftSection={<IconPlus size={16} />} mb="md" onClick={() => setCreating(true)}>New test run</Button>}
      <Card withBorder padding={0}>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>Run</Table.Th><Table.Th>State</Table.Th><Table.Th>Build</Table.Th><Table.Th>Variant</Table.Th><Table.Th>Updated</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {data?.items.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td><ItemLink item={r} withTitle /></Table.Td>
                <Table.Td><StateBadge item={r} /></Table.Td>
                <Table.Td><Text size="sm">{(r.fields.build as string) ?? "–"}</Text></Table.Td>
                <Table.Td><Text size="sm">{(r.fields.variant as string) ?? "–"}</Text></Table.Td>
                <Table.Td><Text size="xs" c="dimmed">{fmtRelative(r.updated_at)}</Text></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
      <ItemFormModal opened={creating} onClose={() => setCreating(false)} defaultType={runType} types={[runType]} />
    </>
  );
}

function Maturity() {
  const { key } = useProjectCtx();
  const [variant, setVariant] = useState<string | null>(null);
  const variants = useFeatureModel(key).data?.variants ?? [];
  const rows = useMaturity(key, variant).data ?? [];
  const count = (k: "specified" | "realised" | "verified" | "validated") => rows.filter((r) => r[k] === "done").length;
  return (
    <>
      <Group mb="md" align="flex-end">
        <Select label="Verification results for variant" placeholder="any variant" clearable value={variant} onChange={setVariant}
          data={variants.map((v) => ({ value: v.key, label: `${v.key} — ${v.title}` }))} />
        <Text size="xs" c="dimmed" maw={520}>
          Specified: allocated requirements are released · Realised: element released · Verified: all allocated requirements passed
          verification on current versions · Validated: the stakeholder needs behind them passed validation.
        </Text>
      </Group>
      <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
        {(["specified", "realised", "verified", "validated"] as const).map((k) => (
          <Card withBorder key={k} padding="sm"><Text size="xs" c="dimmed" tt="uppercase">{k}</Text><Text fw={700} size="lg">{count(k)} / {rows.length}</Text></Card>
        ))}
      </SimpleGrid>
      <Card withBorder padding={0}>
        <Table data-testid="maturity-table">
          <Table.Thead><Table.Tr><Table.Th>Element</Table.Th><Table.Th>Level</Table.Th><Table.Th>State</Table.Th><Table.Th ta="center">Reqs</Table.Th>
            <Table.Th ta="center">Specified</Table.Th><Table.Th ta="center">Realised</Table.Th><Table.Th ta="center">Verified</Table.Th><Table.Th ta="center">Validated</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td><ItemLink item={r} withTitle /></Table.Td>
                <Table.Td><Badge size="xs" variant="outline" color="gray">{r.level ?? "–"}</Badge></Table.Td>
                <Table.Td><Text size="sm">{r.state}</Text></Table.Td>
                <Table.Td ta="center">{r.requirements}</Table.Td>
                <Table.Td ta="center"><MaturityDot value={r.specified} label="Specified" /></Table.Td>
                <Table.Td ta="center"><MaturityDot value={r.realised} label="Realised" /></Table.Td>
                <Table.Td ta="center"><MaturityDot value={r.verified} label="Verified" /></Table.Td>
                <Table.Td ta="center"><MaturityDot value={r.validated} label="Validated" /></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </>
  );
}

function CiImport() {
  const { key, can } = useProjectCtx();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [build, setBuild] = useState("");
  const [environment, setEnvironment] = useState("CI");
  const [variant, setVariant] = useState("");
  const [result, setResult] = useState<{ run: string; matched: number; unmatched: string[]; summary: Record<string, number> } | null>(null);
  const upload = useProjectMutation(key, () => {
    const form = new FormData();
    form.append("file", file!);
    if (build) form.append("build", build);
    if (environment) form.append("environment", environment);
    if (variant) form.append("variant", variant);
    return api.upload<{ run: string; matched: number; unmatched: string[]; summary: Record<string, number> }>(`/projects/${key}/test-runs/import-junit`, form);
  }, { success: (r) => `Created ${r.run}`, onSuccess: (r) => setResult(r) });
  if (!can("contributor")) return <Text c="dimmed">Contributors can import CI results.</Text>;
  return (
    <Card withBorder maw={720}>
      <Stack>
        <Text size="sm">
          Upload a JUnit XML report (the de-facto format of pytest, JUnit, CTest, GoogleTest, …). Results are matched to test cases by
          their <b>Automation ID</b> (<code>classname.name</code> or <code>name</code>) or by an item key in the test name, e.g. <code>test_TC-12_range</code>.
          CI pipelines can call the same endpoint with an API token.
        </Text>
        <FileInput label="JUnit XML" accept=".xml" value={file} onChange={setFile} leftSection={<IconUpload size={16} />} />
        <Group grow>
          <TextInput label="Build / sample" value={build} onChange={(e) => setBuild(e.currentTarget.value)} />
          <TextInput label="Environment" value={environment} onChange={(e) => setEnvironment(e.currentTarget.value)} />
          <TextInput label="Variant key" value={variant} onChange={(e) => setVariant(e.currentTarget.value)} placeholder="VAR-1" />
        </Group>
        <Group><Button onClick={() => upload.mutate(undefined)} disabled={!file} loading={upload.isPending}>Import</Button></Group>
        {result && (
          <Alert color={result.summary.failed ? "orange" : "green"} title={`Test run ${result.run}: ${result.matched} result(s) imported`}>
            <Group gap={6} mb={4}>{Object.entries(result.summary).map(([k, v]) => <Badge key={k}>{k}: {v}</Badge>)}</Group>
            {result.unmatched.length > 0 && <Text size="xs">Unmatched tests: {result.unmatched.slice(0, 10).join(", ")}{result.unmatched.length > 10 ? " …" : ""}</Text>}
            <Button size="xs" variant="light" mt="xs" onClick={() => navigate(`/p/${key}/items/${result.run}?tab=records`)}>Open run</Button>
          </Alert>
        )}
      </Stack>
    </Card>
  );
}
