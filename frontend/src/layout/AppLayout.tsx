import { useState } from "react";
import {
  ActionIcon, AppShell, Avatar, Badge, Box, Burger, Group, Menu, NavLink, Popover, ScrollArea, SimpleGrid,
  Stack, Text, TextInput, Tooltip, UnstyledButton, useComputedColorScheme, useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure, useLocalStorage } from "@mantine/hooks";
import {
  IconActivity, IconAlertTriangle, IconApi, IconBell, IconCalendarStats, IconLayoutKanban, IconTimeline, IconClock, IconBinaryTree, IconChartBar, IconChevronDown, IconFileText, IconFolders,
  IconGitCompare, IconGridDots, IconHome, IconLayoutSidebarLeftCollapse, IconLayoutSidebarLeftExpand, IconListDetails,
  IconLogout, IconLanguage, IconCheck, IconMoon, IconRoute, IconSearch, IconSettings, IconShieldCheck, IconSitemap, IconSun, IconTestPipe,
  IconTopologyStar3, IconUser, IconUsers, type Icon,
} from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInbox, useMe, useProjects } from "@/api/hooks";
import { Logo, LogoMark } from "@/components/Logo";
import { NotificationCenter } from "@/components/NotificationCenter";
import { useLive } from "@/live/LiveProvider";
import { chooseLanguage, LOCALES, locale, tx } from "@/lib/i18n";

interface NavEntry { to: string; label: string; icon: Icon; hint: string }
interface NavGroup { group: string; color: string; items: NavEntry[] }

export const PROJECT_NAV: NavGroup[] = [
  { group: tx("Overview"), color: "navy", items: [
    { to: "", label: tx("Dashboard"), icon: IconHome, hint: tx("Status, coverage and open work") },
    { to: "activity", label: tx("Activity"), icon: IconActivity, hint: tx("Complete audit trail") },
  ] },
  { group: tx("Engineering"), color: "petrol", items: [
    { to: "items", label: tx("Items"), icon: IconListDetails, hint: tx("Requirements, elements, tests — search and edit") },
    { to: "documents", label: tx("Documents"), icon: IconFileText, hint: tx("Live documents, co-editing, Word & ReqIF") },
    { to: "structure", label: tx("Structure"), icon: IconSitemap, hint: tx("Product and system structure") },
    { to: "traceability", label: tx("Traceability"), icon: IconRoute, hint: tx("Matrix, coverage and impact") },
  ] },
  { group: tx("Change & quality"), color: "orange", items: [
    { to: "changes", label: tx("Changes"), icon: IconGitCompare, hint: tx("Change requests and orders") },
    { to: "verification", label: tx("Verification"), icon: IconTestPipe, hint: tx("Tests, runs and results") },
    { to: "risks", label: tx("Risks"), icon: IconAlertTriangle, hint: tx("FMEA: risk matrix, register, mitigation") },
  ] },
  { group: tx("Configuration"), color: "violet", items: [
    { to: "variants", label: tx("Variants"), icon: IconTopologyStar3, hint: tx("Features, variants, 150% model") },
    { to: "baselines", label: tx("Baselines"), icon: IconBinaryTree, hint: tx("Baselines and release collections") },
  ] },
  { group: tx("Planning"), color: "cyan", items: [
    { to: "plans", label: tx("Plans"), icon: IconCalendarStats, hint: tx("Releases, iterations, capacity, planning board") },
    { to: "timeline", label: tx("Timeline"), icon: IconTimeline, hint: tx("Gantt schedule: tasks, milestones, dependencies") },
    { to: "boards", label: tx("Boards"), icon: IconLayoutKanban, hint: tx("Kanban boards over any items") },
    { to: "timesheet", label: tx("Timesheet"), icon: IconClock, hint: tx("Record your working hours per item and day") },
  ] },
  { group: tx("Insights"), color: "blue", items: [
    { to: "reports", label: tx("Reports"), icon: IconChartBar, hint: tx("KPIs and user-built reports") },
  ] },
  { group: tx("Project"), color: "gray", items: [
    { to: "settings", label: tx("Settings"), icon: IconSettings, hint: tx("Members, information model, integrations") },
  ] },
];

function AppLauncher({ projectKey }: { projectKey?: string }) {
  const [opened, setOpened] = useState(false);
  const navigate = useNavigate();
  const projects = useProjects().data ?? [];
  const target = projectKey ?? projects[0]?.key;
  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-start" shadow="lg" width={560} offset={10}>
      <Popover.Target>
        <Tooltip label={tx("Apps")}>
          <ActionIcon variant="subtle" color="gray" size="lg" className="header-icon" onClick={() => setOpened((o) => !o)}
            aria-label={tx("Apps")} data-testid="app-launcher">
            <IconGridDots size={20} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="md">
        <Group justify="space-between" mb="sm">
          <Text fw={600}>{tx("Apps")}</Text>
          {target && <Badge variant="light">{target}</Badge>}
        </Group>
        {!target && <Text size="sm" c="dimmed">{tx("Join a project to use the engineering apps.")}</Text>}
        {target && (
          <Stack gap="sm">
            {PROJECT_NAV.map((g) => (
              <div key={g.group}>
                <Text size="xs" tt="uppercase" fw={600} c="dimmed" mb={4}>{g.group}</Text>
                <SimpleGrid cols={2} spacing={6}>
                  {g.items.map((n) => (
                    <UnstyledButton key={n.to} className="app-tile" data-testid={`app-tile-${n.to || "dashboard"}`}
                      onClick={() => { setOpened(false); navigate(`/p/${target}${n.to ? `/${n.to}` : ""}`); }}>
                      <Group gap="sm" wrap="nowrap">
                        <Box className="app-tile-icon" style={{ background: `var(--mantine-color-${g.color}-7)` }}>
                          <n.icon size={18} color="white" />
                        </Box>
                        <div style={{ minWidth: 0 }}>
                          <Text size="sm" fw={600}>{n.label}</Text>
                          <Text size="xs" c="dimmed" truncate>{n.hint}</Text>
                        </div>
                      </Group>
                    </UnstyledButton>
                  ))}
                </SimpleGrid>
              </div>
            ))}
          </Stack>
        )}
      </Popover.Dropdown>
    </Popover>
  );
}

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  const [collapsed, setCollapsed] = useLocalStorage({ key: "alm-nav-collapsed", defaultValue: false });
  const me = useMe().data!;
  const projects = useProjects().data ?? [];
  const inbox = useInbox().data ?? [];
  const live = useLive();
  const pendingForMe = inbox.filter((r) => r.can_vote).length;
  const match = useMatch("/p/:projectKey/*");
  const projectKey = match?.params.projectKey?.toUpperCase();
  const project = projects.find((p) => p.key === projectKey);
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");
  const rail = collapsed && !opened;

  async function logout() {
    await api.post("/auth/logout");
    qc.clear();
    navigate("/login");
  }

  const section = projectKey ? location.pathname.split("/")[3] ?? "" : null;
  const link = (to: string, label: string, icon: Icon, active: boolean, extra: Record<string, unknown> = {}, right?: React.ReactNode) => {
    const IconC = icon;
    const nav = (
      <NavLink key={to} label={rail ? null : label} leftSection={<IconC size={18} stroke={1.7} />} component={Link} to={to}
        onClick={close} active={active} className="side-link" rightSection={rail ? null : right} {...extra} />
    );
    return rail ? <Tooltip key={to} label={label} position="right">{nav}</Tooltip> : nav;
  };

  return (
    <AppShell className="app-shell" header={{ height: 50 }} padding="md"
      navbar={{ width: rail ? 60 : 236, breakpoint: "sm", collapsed: { mobile: !opened } }}>
      <AppShell.Header className="alm-header">
        <Group h="100%" px="sm" justify="space-between" wrap="nowrap" gap="sm">
          <Group gap={6} wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" color="white" />
            <AppLauncher projectKey={projectKey} />
            <Link to="/" style={{ textDecoration: "none", color: "inherit" }} data-testid="home-link">
              <Box visibleFrom="sm"><Logo inverted /></Box>
              <Box hiddenFrom="sm"><LogoMark /></Box>
            </Link>
            {projectKey && (
              <>
                <Text c="dimmed" visibleFrom="sm" className="header-sep">/</Text>
                <Menu shadow="md" position="bottom-start">
                  <Menu.Target>
                    <UnstyledButton className="context-switcher" data-testid="project-switcher">
                      <Group gap={6} wrap="nowrap">
                        <Text size="sm" fw={600} c="white">{projectKey}</Text>
                        <Text size="sm" c="gray.4" visibleFrom="md" truncate maw={220}>{project?.name}</Text>
                        <IconChevronDown size={14} color="var(--mantine-color-gray-4)" />
                      </Group>
                    </UnstyledButton>
                  </Menu.Target>
                  <Menu.Dropdown>
                    <Menu.Label>{tx("Switch project")}</Menu.Label>
                    {projects.map((p) => (
                      <Menu.Item key={p.key} component={Link} to={`/p/${p.key}`}>
                        <Text size="sm"><b>{p.key}</b> — {p.name}</Text>
                      </Menu.Item>
                    ))}
                  </Menu.Dropdown>
                </Menu>
              </>
            )}
          </Group>
          <Box component="form" visibleFrom="sm" onSubmit={(e) => { e.preventDefault(); if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`); }}
            style={{ flex: "0 1 460px" }}>
            <TextInput placeholder={tx("Search items and documents in all projects…")} leftSection={<IconSearch size={16} />}
              value={q} onChange={(e) => setQ(e.currentTarget.value)} size="sm" classNames={{ input: "header-search" }}
              data-testid="global-search" />
          </Box>
          <Group gap={4} wrap="nowrap">
            <ActionIcon hiddenFrom="sm" variant="subtle" color="gray" size="lg" className="header-icon" component={Link} to="/search"
              aria-label={tx("Search")}><IconSearch size={20} /></ActionIcon>
            <Tooltip label={live.connected ? tx("Live: changes and presence are pushed") : tx("Live connection lost — reconnecting")}>
              <Box className={`live-dot ${live.connected ? "is-on" : ""}`} data-testid="live-indicator" />
            </Tooltip>
            <NotificationCenter />
            <Tooltip label={scheme === "dark" ? tx("Light mode") : tx("Dark mode")}>
              <ActionIcon variant="subtle" color="gray" size="lg" className="header-icon" visibleFrom="sm"
                onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")} aria-label={tx("Toggle color scheme")}>
                {scheme === "dark" ? <IconSun size={20} /> : <IconMoon size={20} />}
              </ActionIcon>
            </Tooltip>
            <Menu shadow="md" position="bottom-end">
              <Menu.Target>
                <Avatar color="petrol" variant="filled" radius="xl" size={30} className="clickable" data-testid="user-menu">
                  {me.display_name.slice(0, 2).toUpperCase()}
                </Avatar>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{me.display_name} ({me.username})</Menu.Label>
                <Menu.Item leftSection={<IconUser size={16} />} component={Link} to="/account">{tx("Account & API tokens")}</Menu.Item>
                {me.is_admin && <Menu.Item leftSection={<IconShieldCheck size={16} />} component={Link} to="/admin">{tx("Administration")}</Menu.Item>}
                <Menu.Item leftSection={<IconApi size={16} />} component="a" href="/api/v1/docs" target="_blank">{tx("REST API docs")}</Menu.Item>
                <Menu.Item leftSection={scheme === "dark" ? <IconSun size={16} /> : <IconMoon size={16} />} hiddenFrom="sm"
                  onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")}>{scheme === "dark" ? tx("Light mode") : tx("Dark mode")}</Menu.Item>
                <Menu.Divider />
                <Menu.Label>{tx("Language")}</Menu.Label>
                {LOCALES.map((l) => (
                  <Menu.Item key={l.value} leftSection={<IconLanguage size={16} />} data-testid={`lang-${l.value}`}
                    rightSection={l.value === locale() ? <IconCheck size={14} /> : null}
                    onClick={() => chooseLanguage(l.value, (v) => api.put("/auth/me/locale", { locale: v }))}>{l.label}</Menu.Item>
                ))}
                <Menu.Divider />
                <Menu.Item leftSection={<IconLogout size={16} />} onClick={logout} data-testid="logout">{tx("Sign out")}</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar className="alm-nav" p={rail ? 6 : "xs"}>
        <AppShell.Section grow component={ScrollArea}>
          {link("/", tx("Home"), IconHome, location.pathname === "/", { "data-testid": "nav-home" })}
          {link("/approvals", tx("My approvals"), IconBell, location.pathname === "/approvals", {},
            pendingForMe ? <Badge size="xs" color="red" circle>{pendingForMe}</Badge> : null)}
          {link("/projects", tx("All projects"), IconFolders, location.pathname === "/projects", { "data-testid": "nav-projects" })}
          {me.is_admin && link("/admin", tx("Administration"), IconUsers, location.pathname === "/admin")}
          {projectKey && PROJECT_NAV.map((g) => (
            <div key={g.group}>
              {rail ? <div className="nav-rule" /> : (
                <Text className="nav-group" size="xs" tt="uppercase" fw={600}>{g.group}{g.group === "Overview" ? ` · ${projectKey}` : ""}</Text>
              )}
              {g.items.map((n) => link(`/p/${projectKey}${n.to ? `/${n.to}` : ""}`, n.label, n.icon, section === n.to,
                { "data-testid": `nav-${n.to || "dashboard"}` }))}
            </div>
          ))}
        </AppShell.Section>
        <AppShell.Section visibleFrom="sm">
          <Tooltip label={rail ? tx("Expand navigation") : tx("Collapse navigation")} position="right">
            <ActionIcon variant="subtle" color="gray" onClick={() => setCollapsed(!collapsed)} m={6} aria-label={tx("Toggle navigation")}
              data-testid="nav-collapse">
              {rail ? <IconLayoutSidebarLeftExpand size={18} /> : <IconLayoutSidebarLeftCollapse size={18} />}
            </ActionIcon>
          </Tooltip>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main className="alm-main">
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
