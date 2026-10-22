import { createContext, useContext, useMemo } from "react";
import { Center, Loader } from "@mantine/core";
import { Outlet, useParams } from "react-router-dom";
import { useConfig, useProject } from "@/api/hooks";
import type { Project, Role } from "@/api/types";
import { Model } from "@/lib/model";
import { NotFound } from "@/components/NotFound";

interface ProjectCtx {
  project: Project;
  model: Model;
  key: string;
  can: (role: Role) => boolean;
}

const Ctx = createContext<ProjectCtx | null>(null);
const RANK: Record<Role, number> = { viewer: 0, contributor: 1, reviewer: 2, manager: 3 };

export function useProjectCtx(): ProjectCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useProjectCtx outside ProjectLayout");
  return ctx;
}

export function ProjectLayout() {
  const { projectKey = "" } = useParams();
  const key = projectKey.toUpperCase();
  const project = useProject(key);
  const config = useConfig(key);
  const value = useMemo<ProjectCtx | null>(() => {
    if (!project.data || !config.data) return null;
    const role = project.data.role;
    return {
      project: project.data,
      model: new Model(config.data.config),
      key,
      can: (r: Role) => role !== null && RANK[role] >= RANK[r],
    };
  }, [project.data, config.data, key]);

  if (project.isError) return <NotFound message={`Project ${key} not found or not accessible.`} />;
  if (!value) return <Center mt={80}><Loader /></Center>;
  return (
    <Ctx.Provider value={value}>
      <Outlet />
    </Ctx.Provider>
  );
}
