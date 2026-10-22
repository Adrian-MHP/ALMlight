import { useState } from "react";
import {
  ActionIcon, AppShell, Avatar, Badge, Burger, Divider, Group, Indicator, Menu, NavLink, ScrollArea, Text, TextInput,
  Tooltip, useComputedColorScheme, useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconActivity, IconApi, IconBinaryTree, IconCheckbox, IconFileText, IconFolders, IconGitCompare, IconHome,
  IconListDetails, IconLogout, IconMoon, IconRoute, IconSearch, IconSettings, IconShieldCheck, IconSitemap, IconSun,
  IconTestPipe, IconTopologyStar3, IconUser, IconUsers,
} from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useInbox, useMe, useProjects } from "@/api/hooks";
import { Logo } from "@/components/Logo";

const PROJECT_NAV = [
  { to: "", label: "Dashboard", icon: IconHome },
  { to: "items", label: "Items", icon: IconListDetails },
  { to: "documents", label: "Documents", icon: IconFileText },
  { to: "structure", label: "Structure", icon: IconSitemap },
  { to: "traceability", label: "Traceability", icon: IconRoute },
  { to: "changes", label: "Changes", icon: IconGitCompare },
  { to: "verification", label: "Verification", icon: IconTestPipe },
  { to: "variants", label: "Variants", icon: IconTopologyStar3 },
  { to: "baselines", label: "Baselines", icon: IconBinaryTree },
  { to: "activity", label: "Activity", icon: IconActivity },
  { to: "settings", label: "Settings", icon: IconSettings },
];

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  const me = useMe().data!;
  const projects = useProjects().data ?? [];
  const inbox = useInbox().data ?? [];
  const pendingForMe = inbox.filter((r) => r.can_vote).length;
  const match = useMatch("/p/:projectKey/*");
  const projectKey = match?.params.projectKey;
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");

  async function logout() {
    await api.post("/auth/logout");
    qc.clear();
    navigate("/login");
  }

  const section = projectKey ? location.pathname.split("/")[3] ?? "" : null;

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 230, breakpoint: "sm", collapsed: { mobile: !opened } }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Link to="/" style={{ textDecoration: "none", color: "inherit" }}><Logo /></Link>
            {projectKey && (
              <Menu shadow="md" position="bottom-start">
                <Menu.Target>
                  <Badge variant="light" size="lg" className="clickable" data-testid="project-switcher">{projectKey}</Badge>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Label>Switch project</Menu.Label>
                  {projects.map((p) => (
                    <Menu.Item key={p.key} component={Link} to={`/p/${p.key}`}>
                      <Text size="sm"><b>{p.key}</b> — {p.name}</Text>
                    </Menu.Item>
                  ))}
                </Menu.Dropdown>
              </Menu>
            )}
          </Group>
          <Group gap="xs" wrap="nowrap">
            <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`); }}>
              <TextInput placeholder="Search all projects…" leftSection={<IconSearch size={16} />} value={q}
                onChange={(e) => setQ(e.currentTarget.value)} w={{ base: 140, md: 280 }} size="sm" data-testid="global-search" />
            </form>
            <Tooltip label="Approvals">
              <Indicator disabled={pendingForMe === 0} label={pendingForMe} size={16} color="red">
                <ActionIcon variant="subtle" size="lg" component={Link} to="/approvals" aria-label="Approvals">
                  <IconCheckbox size={20} />
                </ActionIcon>
              </Indicator>
            </Tooltip>
            <Tooltip label={scheme === "dark" ? "Light mode" : "Dark mode"}>
              <ActionIcon variant="subtle" size="lg" onClick={() => setColorScheme(scheme === "dark" ? "light" : "dark")}
                aria-label="Toggle color scheme">
                {scheme === "dark" ? <IconSun size={20} /> : <IconMoon size={20} />}
              </ActionIcon>
            </Tooltip>
            <Menu shadow="md" position="bottom-end">
              <Menu.Target>
                <Avatar color="indigo" radius="xl" size={32} className="clickable" data-testid="user-menu">
                  {me.display_name.slice(0, 2).toUpperCase()}
                </Avatar>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{me.display_name} ({me.username})</Menu.Label>
                <Menu.Item leftSection={<IconUser size={16} />} component={Link} to="/account">Account & API tokens</Menu.Item>
                {me.is_admin && <Menu.Item leftSection={<IconShieldCheck size={16} />} component={Link} to="/admin">Administration</Menu.Item>}
                <Menu.Item leftSection={<IconApi size={16} />} component="a" href="/api/v1/docs" target="_blank">REST API docs</Menu.Item>
                <Menu.Divider />
                <Menu.Item leftSection={<IconLogout size={16} />} onClick={logout} data-testid="logout">Sign out</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        <ScrollArea>
          <NavLink label="All projects" leftSection={<IconFolders size={18} />} component={Link} to="/" onClick={close}
            active={location.pathname === "/"} />
          <NavLink label="Approvals" leftSection={<IconCheckbox size={18} />} component={Link} to="/approvals" onClick={close}
            active={location.pathname === "/approvals"}
            rightSection={pendingForMe ? <Badge size="xs" color="red" circle>{pendingForMe}</Badge> : null} />
          {me.is_admin && (
            <NavLink label="Administration" leftSection={<IconUsers size={18} />} component={Link} to="/admin" onClick={close}
              active={location.pathname === "/admin"} />
          )}
          {projectKey && (
            <>
              <Divider my="sm" label={projectKey} labelPosition="left" />
              {PROJECT_NAV.map((n) => (
                <NavLink key={n.to} label={n.label} leftSection={<n.icon size={18} />} component={Link}
                  to={`/p/${projectKey}${n.to ? `/${n.to}` : ""}`} onClick={close} active={section === n.to}
                  data-testid={`nav-${n.to || "dashboard"}`} />
              ))}
            </>
          )}
        </ScrollArea>
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
