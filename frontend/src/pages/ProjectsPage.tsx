import { useState } from "react";
import { Badge, Box, Button, Card, Group, Modal, Select, SimpleGrid, Stack, Text, Textarea, TextInput } from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useMe, useProjectMutation, useProjects, useTemplates } from "@/api/hooks";
import type { Project } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { useQueryClient } from "@tanstack/react-query";

export function ProjectsPage() {
  const me = useMe().data!;
  const { data: projects = [], isLoading } = useProjects();
  const [open, setOpen] = useState(false);
  return (
    <>
      <PageHeader title="All projects" subtitle="Engineering projects you are a member of"
        actions={me.is_admin && <Button leftSection={<IconPlus size={16} />} onClick={() => setOpen(true)} data-testid="new-project">New project</Button>} />
      {!isLoading && projects.length === 0 && (
        <Card withBorder p="xl"><Text c="dimmed">No projects yet. {me.is_admin ? "Create the first one." : "Ask an administrator to add you to a project."}</Text></Card>
      )}
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {projects.map((p) => <ProjectCard key={p.key} p={p} />)}
      </SimpleGrid>
      <CreateProjectModal opened={open} onClose={() => setOpen(false)} />
    </>
  );
}

export function ProjectCard({ p }: { p: Project }) {
  return (
    <Card withBorder padding="md" component={Link} to={`/p/${p.key}`} className="project-card" data-testid={`project-card-${p.key}`}>
      <Group justify="space-between" mb={6} wrap="nowrap">
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
          <Box className="project-badge">{p.key.slice(0, 2)}</Box>
          <div style={{ minWidth: 0, flex: 1 }}>
            <Text fw={600} truncate>{p.name}</Text>
            <Text size="xs" c="dimmed" className="mono">{p.key}</Text>
          </div>
        </Group>
        {p.role && <Badge variant="light" color="gray" style={{ flexShrink: 0, maxWidth: "none" }}>{p.role}</Badge>}
      </Group>
      <Text size="sm" c="dimmed" lineClamp={2}>{p.description || "—"}</Text>
      <Text size="xs" c="dimmed" mt="sm">Process template: {p.template_key}</Text>
    </Card>
  );
}

function CreateProjectModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const templates = useTemplates().data ?? [];
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState<string | null>("systems_engineering");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const create = useProjectMutation(null, () => api.post<Project>("/projects", { key, name, description, template }), {
    success: "Project created",
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ["projects"] }); qc.invalidateQueries({ queryKey: ["me"] }); onClose(); navigate(`/p/${p.key}`); },
  });
  const tpl = templates.find((t) => t.key === template);
  return (
    <Modal opened={opened} onClose={onClose} title="New project" size="lg">
      <Stack>
        <Group grow align="flex-start">
          <TextInput label="Key" description="2–16 characters, e.g. SENSOR" value={key} required maxLength={16}
            onChange={(e) => setKey(e.currentTarget.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} data-testid="project-key" />
          <TextInput label="Name" value={name} required onChange={(e) => setName(e.currentTarget.value)} data-testid="project-name" />
        </Group>
        <Textarea label="Description" value={description} onChange={(e) => setDescription(e.currentTarget.value)} autosize minRows={2} />
        <Select label="Process template" description="Information model: item types, links and workflows (can be tailored later)"
          data={templates.map((t) => ({ value: t.key, label: t.label }))} value={template} onChange={setTemplate} allowDeselect={false} />
        {tpl && <Text size="xs" c="dimmed">{tpl.description} Item types: {tpl.item_types.join(", ")}.</Text>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button onClick={() => create.mutate(undefined)} loading={create.isPending} disabled={key.length < 2 || !name.trim()}
            data-testid="project-create">Create</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
