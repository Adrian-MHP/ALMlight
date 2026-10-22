// React Query hooks. All project-scoped queries live under ["p", projectKey, ...] so a mutation
// can refresh everything that may have changed with one invalidation.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notifications } from "@mantine/notifications";
import { api, ApiError, qs } from "./client";
import type {
  AdminUser, ApiToken, ApprovalRequest, AuditEntry, Baseline, BaselineCompare, BaselineDetail, Comment, Coverage,
  ExternalRef, FeatureModel, HistoryEntry, ImpactResult, Integrations, Item, ItemDetail, LinkView, MaturityRow, Me,
  Member, Page, Project, ProjectConfig, Resolved, Stats, SuspectLink, TemplateInfo, TestRecord, TransitionOption,
  TreeNode, UserRef, VerificationInfo, Version, BranchInfo, MergePreview, Report, ReportSummary, ReportTemplate,
  ReportWidget, WidgetData,
} from "./types";

export const pk = (projectKey: string, ...rest: unknown[]) => ["p", projectKey, ...rest];

export function useMe() {
  return useQuery<Me, ApiError>({ queryKey: ["me"], queryFn: () => api.get("/auth/me"), retry: false });
}

export function useProjects() {
  return useQuery<Project[]>({ queryKey: ["projects"], queryFn: () => api.get("/projects") });
}

export function useTemplates() {
  return useQuery<TemplateInfo[]>({ queryKey: ["templates"], queryFn: () => api.get("/templates") });
}

export function useProject(key: string) {
  return useQuery<Project, ApiError>({ queryKey: pk(key, "project"), queryFn: () => api.get(`/projects/${key}`) });
}

export function useConfig(key: string) {
  return useQuery<{ version: number; config: ProjectConfig }>({
    queryKey: pk(key, "config"),
    queryFn: () => api.get(`/projects/${key}/config`),
    staleTime: 60_000,
  });
}

export function useStats(key: string) {
  return useQuery<Stats>({ queryKey: pk(key, "stats"), queryFn: () => api.get(`/projects/${key}/stats`) });
}

export interface ItemFilter {
  q?: string;
  type?: string[];
  state?: string[];
  suspect?: boolean;
  owner?: string;
  sort?: string;
  limit?: number;
  offset?: number;
  fields?: Record<string, string>;
}

export function useItems(key: string, f: ItemFilter, enabled = true) {
  const fieldParams = Object.fromEntries(Object.entries(f.fields ?? {}).map(([k, v]) => [`field.${k}`, v]));
  const query = qs({ q: f.q, type: f.type, state: f.state, suspect: f.suspect || undefined, owner: f.owner,
    sort: f.sort, limit: f.limit ?? 50, offset: f.offset ?? 0, ...fieldParams });
  return useQuery<Page<Item>>({
    queryKey: pk(key, "items", query),
    queryFn: () => api.get(`/projects/${key}/items${query}`),
    enabled,
    placeholderData: (prev) => prev,
  });
}

export function useItem(key: string, itemKey: string, enabled = true) {
  return useQuery<ItemDetail, ApiError>({
    queryKey: pk(key, "item", itemKey),
    queryFn: () => api.get(`/projects/${key}/items/${itemKey}`),
    enabled,
  });
}

const itemQuery = <T,>(name: string, path: string) =>
  (key: string, itemKey: string, enabled = true) =>
    useQuery<T>({
      queryKey: pk(key, "item", itemKey, name),
      queryFn: () => api.get(`/projects/${key}/items/${itemKey}${path}`),
      enabled,
    });

export const useLinks = itemQuery<LinkView[]>("links", "/links");
export const useTransitions = itemQuery<TransitionOption[]>("transitions", "/transitions");
export const useVersions = itemQuery<Version[]>("versions", "/versions");
export const useHistory = itemQuery<HistoryEntry[]>("history", "/history");
export const useItemApprovals = itemQuery<ApprovalRequest[]>("approvals", "/approvals");
export const useComments = itemQuery<Comment[]>("comments", "/comments");
export const useRefs = itemQuery<ExternalRef[]>("refs", "/external-refs");
export const useImpact = itemQuery<ImpactResult>("impact", "/impact");
export const useVerification = itemQuery<VerificationInfo>("verification", "/verification");

export function useTree(key: string, itemKey: string | null, content = false) {
  return useQuery<TreeNode>({
    queryKey: pk(key, "tree", itemKey, content),
    queryFn: () => api.get(`/projects/${key}/items/${itemKey}/tree${content ? "?content=true" : ""}`),
    enabled: !!itemKey,
  });
}

export function useDiff(key: string, itemKey: string, from: number | null, to: number | null) {
  return useQuery<{ from: string; to: string; changes: import("./types").Change[] }>({
    queryKey: pk(key, "item", itemKey, "diff", from, to),
    queryFn: () => api.get(`/projects/${key}/items/${itemKey}/diff?from=${from}&to=${to}`),
    enabled: from !== null && to !== null,
  });
}

export function useRecords(key: string, runKey: string, enabled = true) {
  return useQuery<TestRecord[]>({
    queryKey: pk(key, "item", runKey, "records"),
    queryFn: () => api.get(`/projects/${key}/test-runs/${runKey}/records`),
    enabled,
  });
}

export function useInbox(status = "pending", mine = true) {
  return useQuery<ApprovalRequest[]>({
    queryKey: ["inbox", status, mine],
    queryFn: () => api.get(`/approvals${qs({ status, mine })}`),
    refetchInterval: 60_000,
  });
}

export function useSuspects(key: string) {
  return useQuery<SuspectLink[]>({ queryKey: pk(key, "suspects"), queryFn: () => api.get(`/projects/${key}/suspects`) });
}

export function useCoverage(key: string, type: string | null, variant?: string | null) {
  return useQuery<Coverage>({
    queryKey: pk(key, "coverage", type, variant),
    queryFn: () => api.get(`/projects/${key}/coverage${qs({ type: type ?? "", variant })}`),
    enabled: !!type,
  });
}

export function useMaturity(key: string, variant?: string | null) {
  return useQuery<MaturityRow[]>({
    queryKey: pk(key, "maturity", variant),
    queryFn: () => api.get(`/projects/${key}/maturity${qs({ variant })}`),
  });
}

export function useTraceMatrix(key: string, rows: string | null, cols: string | null) {
  return useQuery<{ rows: { id: string; key: string; title: string }[]; cols: { id: string; key: string; title: string }[];
    cells: { row: string; col: string; type: string; suspect: boolean }[] }>({
    queryKey: pk(key, "matrix", rows, cols),
    queryFn: () => api.get(`/projects/${key}/trace-matrix${qs({ rows: rows ?? "", cols: cols ?? "" })}`),
    enabled: !!rows && !!cols,
  });
}

export function useBaselines(key: string) {
  return useQuery<Baseline[]>({ queryKey: pk(key, "baselines"), queryFn: () => api.get(`/projects/${key}/baselines`) });
}

export function useBaseline(key: string, id: string | null) {
  return useQuery<BaselineDetail>({
    queryKey: pk(key, "baseline", id),
    queryFn: () => api.get(`/projects/${key}/baselines/${id}`),
    enabled: !!id,
  });
}

export function useBaselineCompare(key: string, a: string | null, b: string | null) {
  return useQuery<BaselineCompare>({
    queryKey: pk(key, "compare", a, b),
    queryFn: () => api.get(`/projects/${key}/baselines/${a}/compare${qs({ to: b ?? undefined })}`),
    enabled: !!a,
  });
}

export function useFeatureModel(key: string) {
  return useQuery<FeatureModel>({
    queryKey: pk(key, "features"),
    queryFn: () => api.get(`/projects/${key}/variants/feature-model`),
  });
}

export function useResolve(key: string, selection: string[] | null) {
  return useQuery<Resolved>({
    queryKey: pk(key, "resolve", selection),
    queryFn: () => api.post(`/projects/${key}/variants/configure`, { selection }),
    enabled: selection !== null,
    placeholderData: (prev) => prev,
  });
}

export function useAudit(key: string, action?: string | null) {
  return useQuery<AuditEntry[]>({
    queryKey: pk(key, "audit", action),
    queryFn: () => api.get(`/projects/${key}/audit${qs({ action, limit: 300 })}`),
  });
}

export function useMembers(key: string) {
  return useQuery<Member[]>({ queryKey: pk(key, "members"), queryFn: () => api.get(`/projects/${key}/members`) });
}

export function useDirectory() {
  return useQuery<UserRef[]>({ queryKey: ["directory"], queryFn: () => api.get("/users/directory"), staleTime: 60_000 });
}

export function useUsers(enabled = true) {
  return useQuery<AdminUser[]>({ queryKey: ["users"], queryFn: () => api.get("/users"), enabled });
}

export function useTokens() {
  return useQuery<ApiToken[]>({ queryKey: ["tokens"], queryFn: () => api.get("/auth/tokens") });
}

export function useIntegrations(key: string, enabled = true) {
  return useQuery<Integrations>({
    queryKey: pk(key, "integrations"),
    queryFn: () => api.get(`/projects/${key}/integrations`),
    enabled,
  });
}

export function useSearch(q: string) {
  return useQuery<Item[]>({ queryKey: ["search", q], queryFn: () => api.get(`/search${qs({ q })}`), enabled: q.length > 1 });
}

/** A mutation that refreshes the project's queries on success and shows errors as notifications. */
export function useProjectMutation<TVars, TResult = unknown>(
  projectKey: string | null,
  fn: (vars: TVars) => Promise<TResult>,
  opts: { success?: string | ((r: TResult) => string); onSuccess?: (r: TResult, v: TVars) => void; silentError?: boolean } = {},
) {
  const qc = useQueryClient();
  return useMutation<TResult, ApiError, TVars>({
    mutationFn: fn,
    onSuccess: (result, vars) => {
      if (projectKey) qc.invalidateQueries({ queryKey: ["p", projectKey] });
      qc.invalidateQueries({ queryKey: ["inbox"] });
      if (opts.success) {
        notifications.show({ color: "teal", message: typeof opts.success === "function" ? opts.success(result) : opts.success });
      }
      opts.onSuccess?.(result, vars);
    },
    onError: (err) => {
      if (!opts.silentError) notifications.show({ color: "red", title: "Action failed", message: err.full ?? err.message });
    },
  });
}

export const useItemBranches = itemQuery<BranchInfo[]>("branches", "/branches");

export function useMergePreview(key: string, branchId: string | null) {
  return useQuery<MergePreview>({
    queryKey: pk(key, "merge-preview", branchId),
    queryFn: () => api.get(`/projects/${key}/branches/${branchId}/preview`),
    enabled: !!branchId,
  });
}

export function useReports(key: string) {
  return useQuery<ReportSummary[]>({ queryKey: pk(key, "reports"), queryFn: () => api.get(`/projects/${key}/reports`) });
}

export function useReportTemplates(key: string) {
  return useQuery<ReportTemplate[]>({ queryKey: pk(key, "report-templates"), queryFn: () => api.get(`/projects/${key}/report-templates`) });
}

export function useReport(key: string, id: string) {
  return useQuery<Report>({ queryKey: pk(key, "report", id), queryFn: () => api.get(`/projects/${key}/reports/${id}`) });
}

export function useReportData(key: string, id: string, enabled = true) {
  return useQuery<Record<string, WidgetData>>({
    queryKey: pk(key, "report", id, "data"),
    queryFn: () => api.get(`/projects/${key}/reports/${id}/data`),
    enabled,
  });
}

/** Live evaluation of a (possibly unsaved) widget definition. */
export function useWidgetPreview(key: string, widget: ReportWidget | null) {
  return useQuery<WidgetData>({
    queryKey: pk(key, "widget-preview", widget),
    queryFn: () => api.post(`/projects/${key}/reports/preview-widget`, widget),
    enabled: !!widget,
    placeholderData: (prev) => prev,
  });
}
