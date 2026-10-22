import { Anchor, Badge, Button, Card, Grid, Group, SimpleGrid, Stack, Text, ThemeIcon, Title } from "@mantine/core";
import { IconBell, IconClock, IconFileText, IconFolders, IconListDetails, IconUsers } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { useInbox, useMe, useProjects } from "@/api/hooks";
import { TAGLINE } from "@/lib/product";
import { useRecent } from "@/lib/recent";
import { fmtDateTime } from "@/lib/format";
import { ProjectCard } from "./ProjectsPage";

function greeting(): string {
  const h = new Date().getHours();
  return h < 11 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function Tile({ icon: Icon, label, value, to, color, testId }: {
  icon: typeof IconBell; label: string; value: string | number; to: string; color: string; testId?: string;
}) {
  return (
    <Card withBorder padding="md" component={Link} to={to} className="ws-tile" data-testid={testId}>
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Text size="xs" tt="uppercase" fw={600} c="dimmed">{label}</Text>
          <Text fz={28} fw={650} lh={1.2}>{value}</Text>
        </div>
        <ThemeIcon size={44} radius="sm" color={color} variant="light"><Icon size={24} /></ThemeIcon>
      </Group>
    </Card>
  );
}

/** "My workspace": what needs my attention across all projects. */
export function HomePage() {
  const me = useMe().data!;
  const projects = useProjects().data ?? [];
  const inbox = useInbox().data ?? [];
  const mine = inbox.filter((r) => r.can_vote);
  const [recent, clearRecent] = useRecent();
  return (
    <Stack gap="md">
      <div className="ws-hero">
        <Title order={2} data-testid="home-greeting">{greeting()}, {me.display_name.split(" ")[0]}</Title>
        <Text c="dimmed" size="sm">{TAGLINE}</Text>
      </div>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
        <Tile icon={IconBell} label="Approvals for me" value={mine.length} to="/approvals" color={mine.length ? "red" : "gray"} testId="tile-approvals" />
        <Tile icon={IconFolders} label="Projects" value={projects.length} to="/projects" color="petrol" testId="tile-projects" />
        <Tile icon={IconClock} label="Recently opened" value={recent.length} to="#recent" color="navy" />
        <Tile icon={IconUsers} label="Pending reviews" value={inbox.length} to="/approvals" color="orange" />
      </SimpleGrid>
      <Grid>
        <Grid.Col span={{ base: 12, lg: 8 }}>
          <Group justify="space-between" mb="xs">
            <Title order={4}>Your projects</Title>
            <Anchor component={Link} to="/projects" size="sm">All projects</Anchor>
          </Group>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            {projects.map((p) => <ProjectCard key={p.key} p={p} />)}
          </SimpleGrid>
          {projects.length === 0 && <Card withBorder p="xl"><Text c="dimmed">You are not a member of any project yet.</Text></Card>}
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <Card withBorder mb="md" id="recent">
            <Group justify="space-between" mb="xs">
              <Text fw={600}>Recently opened</Text>
              {recent.length > 0 && <Button size="compact-xs" variant="subtle" color="gray" onClick={clearRecent}>Clear</Button>}
            </Group>
            <Stack gap={6}>
              {recent.length === 0 && <Text size="sm" c="dimmed">Items and documents you open appear here.</Text>}
              {recent.map((r) => (
                <Group key={`${r.project}-${r.kind}-${r.key}`} gap="xs" wrap="nowrap">
                  {r.kind === "document" ? <IconFileText size={16} /> : <IconListDetails size={16} />}
                  <Anchor component={Link} size="sm" className="item-key"
                    to={r.kind === "document" ? `/p/${r.project}/documents/${r.key}` : `/p/${r.project}/items/${r.key}`}>{r.key}</Anchor>
                  <Text size="sm" truncate style={{ flex: 1 }}>{r.title}</Text>
                  <Badge size="xs" variant="outline" color="gray">{r.project}</Badge>
                </Group>
              ))}
            </Stack>
          </Card>
          <Card withBorder>
            <Group justify="space-between" mb="xs">
              <Text fw={600}>Waiting for my approval</Text>
              <Anchor component={Link} to="/approvals" size="sm">Open inbox</Anchor>
            </Group>
            <Stack gap={6}>
              {mine.length === 0 && <Text size="sm" c="dimmed">Nothing to approve right now.</Text>}
              {mine.slice(0, 6).map((r) => (
                <Group key={r.id} gap="xs" wrap="nowrap">
                  <Anchor component={Link} to={`/p/${r.project_key}/items/${r.item_key}`} size="sm" className="item-key">{r.item_key}</Anchor>
                  <Text size="sm" truncate style={{ flex: 1 }}>{r.label} · {r.item_title}</Text>
                  <Text size="xs" c="dimmed">{fmtDateTime(r.created_at)}</Text>
                </Group>
              ))}
            </Stack>
          </Card>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
