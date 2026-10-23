// Types mirroring the REST API (see /api/v1/docs).

export type Role = "viewer" | "contributor" | "reviewer" | "manager";

export interface UserRef {
  id: string;
  username: string;
  display_name: string;
}

export interface Me {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  is_admin: boolean;
  projects: Record<string, Role>;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Project {
  id: string;
  key: string;
  name: string;
  description: string | null;
  template_key: string;
  config_version: number;
  role: Role | null;
  created_at: string;
}

export interface TemplateInfo {
  key: string;
  label: string;
  description: string | null;
  item_types: string[];
}

// --- information model ---------------------------------------------------------------------

export type FieldType =
  | "string" | "text" | "integer" | "number" | "boolean" | "date" | "enum" | "multienum" | "tags" | "user" | "url" | "steps";

export interface EnumOption {
  key: string;
  label: string;
  color?: string | null;
}

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  required: boolean;
  options: EnumOption[];
  default: unknown;
  pattern?: string | null;
  help?: string | null;
  min?: number | null;
  max?: number | null;
  formula?: string | null;
  classify?: { field: string; bands: [number, string][] } | null;
}

export interface TestStep { step: string; expected: string }

export interface StateDef {
  key: string;
  label: string;
  category: string;
  initial: boolean;
  frozen: boolean;
  released: boolean;
  implementation_open: boolean;
  color?: string | null;
}

export interface ApprovalDef {
  roles: Role[];
  count: number;
  signature: boolean;
  allow_self_approval: boolean;
  reject_to?: string | null;
}

export interface TransitionDef {
  key: string;
  label: string;
  from: string[];
  to: string;
  min_role: Role;
  approval?: ApprovalDef | null;
  signature: boolean;
  comment_required: boolean;
  guards: string[];
  effects: string[];
}

export interface WorkflowDef {
  key: string;
  label: string;
  states: StateDef[];
  transitions: TransitionDef[];
}

export type ItemCategory = "requirement" | "architecture" | "verification" | "change" | "document" | "variability" | "risk"
  | "planning" | "other";

export interface ItemTypeDef {
  key: string;
  label: string;
  prefix: string;
  category: ItemCategory;
  description?: string | null;
  icon?: string | null;
  color?: string | null;
  workflow?: string | null;
  change_controlled: boolean;
  document: boolean;
  fields: FieldDef[];
}

export interface LinkTypeDef {
  key: string;
  label: string;
  reverse_label: string;
  description?: string | null;
  sources: string[];
  targets: string[];
  structural: boolean;
  acyclic: boolean;
  suspect_on_target_change: boolean;
  editable_on_frozen_source: boolean;
  attributes: FieldDef[];
}

export interface Semantics {
  affects_link: string;
  implements_link: string;
  verifies_link: string;
  satisfies_link: string;
  derives_link: string;
  requires_link: string;
  excludes_link: string;
  heading_type: string | null;
  test_case_types: string[];
  test_run_type: string | null;
  stakeholder_types: string[];
  element_types: string[];
  test_steps_field: string;
  defect_type: string | null;
  risk_type: string | null;
  mitigation_link: string;
  release_type: string | null;
  planned_link: string;
  subplan_link?: string;
  dependency_link?: string;
  task_type?: string | null;
  estimate_field?: string;
  capacity_field?: string;
}

export interface ProjectConfig {
  key: string;
  label: string;
  description?: string | null;
  version: number;
  revision_scheme: "letters" | "numbers";
  item_types: ItemTypeDef[];
  link_types: LinkTypeDef[];
  workflows: WorkflowDef[];
  semantics: Semantics;
}

// --- items --------------------------------------------------------------------------------

export interface Lifecycle {
  state: string | null;
  label: string | null;
  category: string | null;
  color: string | null;
  frozen: boolean;
  released: boolean;
}

export interface Item {
  id: string;
  key: string;
  project_key: string;
  type_key: string;
  title: string;
  lifecycle: Lifecycle;
  revision: string;
  iteration: number;
  version: string;
  version_no: number;
  fields: Record<string, unknown>;
  applicability: string | null;
  owner: UserRef | null;
  updated_at: string;
  created_at?: string | null;
  author?: UserRef | null;
}

export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  uploaded_by?: string | null;
  uploaded_at?: string | null;
  revision: number;
  comment?: string | null;
  checked_out_by?: UserRef | null;
  checked_out_at?: string | null;
  checkout_note?: string | null;
}

export interface FileRevision extends Omit<Attachment, "uploaded_by"> {
  uploaded_by: UserRef | null;
  version_no: number;
  item_version: string;
}

export interface MyCheckout {
  project: string; item_key: string; item_title: string; attachment_id: string; filename: string;
  revision: number; note: string | null; checked_out_at: string;
}

export interface ItemDetail extends Item {
  description: string;
  content_hash: string;
  attachments: Attachment[];
  released_version: string | null;
  created_by: UserRef | null;
  created_at: string;
  updated_by: UserRef | null;
  change_order: string | null;
}

export interface Version {
  version_no: number;
  version: string;
  revision: string;
  iteration: number;
  kind: string;
  title: string;
  description: string;
  fields: Record<string, unknown>;
  applicability: string | null;
  attachments: Attachment[];
  state: string | null;
  change_note: string | null;
  change_order: string | null;
  created_by: UserRef | null;
  created_at: string;
  released: boolean;
}

export interface Change {
  field: string;
  old: unknown;
  new: unknown;
  diff?: string[];
  html_diff?: string;
}

export interface HistoryEntry {
  id: number;
  ts: string;
  actor: string;
  action: string;
  summary: string;
  details: Record<string, unknown>;
}

export interface LinkView {
  id: string;
  type: string;
  label: string;
  direction: "outgoing" | "incoming";
  position: number | null;
  attributes: Record<string, unknown>;
  applicability: string | null;
  suspect: boolean;
  suspect_reason: string | null;
  other: Item;
}

export interface TransitionOption {
  key: string;
  label: string;
  to: string;
  to_label: string;
  min_role: Role;
  allowed: boolean;
  blocked_by: string[];
  comment_required: boolean;
  signature: boolean;
  approval: ApprovalDef | null;
  pending_request_id: string | null;
}

export interface ApprovalRequest {
  id: string;
  project_key: string;
  item_key: string;
  item_title: string;
  item_type: string;
  transition: string;
  label: string;
  from_state: string;
  to_state: string;
  version_no: number;
  status: "pending" | "approved" | "rejected" | "cancelled";
  required: number;
  roles: Role[];
  signature_required: boolean;
  comment: string | null;
  requested_by: UserRef | null;
  created_at: string;
  resolved_at: string | null;
  votes: { user: UserRef | null; decision: string; comment: string | null; signed: boolean; meaning: string; at: string }[];
  can_vote: boolean;
  cannot_vote_reason: string | null;
}

export interface Comment {
  id: string;
  author: UserRef | null;
  body: string;
  created_at: string;
}

export interface ExternalRef {
  id: string;
  system: string;
  kind: string;
  external_id: string;
  url: string | null;
  title: string | null;
  status: string | null;
  data: Record<string, unknown>;
  updated_at: string;
}

export interface TreeNode extends Item {
  description?: string;
  link?: { id: string; type: string; position: number | null; attributes: Record<string, unknown>; applicability: string | null; suspect: boolean };
  children: TreeNode[];
}

export interface ImpactResult {
  root: string;
  count: number;
  by_type: Record<string, number>;
  impacted: { item: Item; depth: number; via: string; via_item: string | null; relation: "depends" | "where_used" }[];
}

export interface SuspectLink {
  link_id: string;
  type: string;
  source: string;
  source_title: string;
  target: string;
  target_title: string;
  reason: string | null;
  since: string | null;
}

export interface Baseline {
  id: string;
  name: string;
  description: string | null;
  scope: string | null;
  revision_rule: "latest" | "released";
  item_count: number;
  link_count: number;
  created_by: UserRef | null;
  created_at: string;
}

export interface BaselineDetail extends Baseline {
  items: { id: string; key: string; type_key: string; title: string; version: string; version_no: number; state: string | null; current_version: string; deleted: boolean }[];
}

export interface BaselineCompare {
  from: { id: string; name: string };
  to: { id: string | null; name: string };
  items: {
    added: { key: string; type_key: string; title: string; version: string }[];
    removed: { key: string; type_key: string; title: string; version: string }[];
    changed: { key: string; type_key: string; title: string; from_version: string; to_version: string; changes: Change[] }[];
    unchanged: number;
  };
  links: { added: { type: string; source: string; target: string }[]; removed: { type: string; source: string; target: string }[] };
}

export interface CoverageRow {
  id: string;
  key: string;
  title: string;
  state: string | null;
  state_label: string | null;
  version: string;
  refined_by: number;
  satisfied_by: number;
  verified_by: number;
  suspect_links: number;
  verification: VerificationStatus;
}

export type VerificationStatus = "passed" | "failed" | "retest" | "not_run" | "none";

export interface Coverage {
  type: string;
  total: number;
  allocated_pct: number;
  refined_pct: number;
  verified_pct: number;
  with_tests_pct: number;
  rows: CoverageRow[];
}

export interface MaturityRow {
  id: string;
  key: string;
  title: string;
  level: string | null;
  state: string | null;
  version: string;
  requirements: number;
  specified: "done" | "partial" | "none";
  realised: "done" | "partial" | "none";
  verified: "done" | "partial" | "none";
  validated: "done" | "partial" | "none";
}

export interface VerificationInfo {
  status: VerificationStatus;
  tests: { key: string; title: string; status: VerificationStatus; suspect: boolean; result: string | null; executed_at: string | null; tested_version: string | null }[];
}

export interface TestRecord {
  id: string;
  test_case: string;
  title: string;
  result: "not_run" | "passed" | "failed" | "blocked" | "skipped";
  comment: string | null;
  tested_version: string;
  tested_version_no: number;
  current_version: string;
  outdated: boolean;
  duration_ms: number | null;
  executed_by: UserRef | null;
  executed_at: string | null;
  steps: TestStep[];
  step_results: { result: string; actual: string; comment: string }[];
  defect: string | null;
}

export interface FeatureNode {
  code: string;
  key: string;
  title: string;
  kind: "mandatory" | "optional";
  group: "none" | "alternative" | "or";
  obsolete: boolean;
  children: FeatureNode[];
}

export interface FeatureModel {
  roots: FeatureNode[];
  requires: { from: string; to: string }[];
  excludes: { from: string; to: string }[];
  variants: { key: string; title: string; selection: string[]; state: string | null; errors: string[] }[];
  unknown_codes: { key: string; missing: string[] }[];
}

export interface Resolved {
  selection: string[];
  errors: string[];
  counts: Record<string, { included: number; excluded: number }>;
  included: Item[];
  excluded: Item[];
  invalid: string[];
  excluded_link_ids: string[];
  variant?: { key: string; title: string };
}

export interface Stats {
  items_by_type: Record<string, Record<string, number>>;
  suspect_links: number;
  pending_approvals: number;
  open_changes: number;
  total_items: number;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string;
  details: Record<string, unknown>;
  hash: string;
}

export interface Member {
  user_id: string;
  username: string;
  display_name: string;
  role: Role;
  active: boolean;
}

export interface AdminUser {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface ApiToken {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  token?: string;
}

export interface Integrations {
  inbound: { system: string; enabled: boolean; endpoint: string }[];
  webhooks: { id: string; url: string; events: string[]; active: boolean }[];
  events: string[];
}

export interface ImportResult {
  dry_run: boolean;
  applied: boolean;
  rows: number;
  summary: Record<string, number>;
  results: { row: number; action: string; key?: string; error?: string }[];
}

export interface BranchInfo {
  id: string;
  name: string;
  description: string | null;
  source_root: string | null;
  branch_root: string | null;
  created_at: string;
  last_merged_at: string | null;
}

export interface MergeChange {
  field: string;
  base: unknown;
  source: unknown;
  branch: unknown;
  kind: "source" | "branch" | "same" | "conflict";
}

export interface MergePreview {
  branch: BranchInfo;
  pairs: {
    source: string;
    branch: string;
    type_key: string;
    title: string;
    source_version: string;
    branch_version: string;
    status: "conflict" | "both_changed" | "branch_changed" | "source_changed" | "deleted_in_branch" | "deleted_in_source" | "unchanged";
    changes: MergeChange[];
  }[];
  added_in_branch: { branch: string; type_key: string; title: string; parent_in_source: string | null }[];
}

// --- reports -----------------------------------------------------------------------------------

export type WidgetType =
  | "kpi" | "chart" | "table" | "trend" | "coverage" | "matrix" | "markdown"
  | "reuse" | "change_lead_time" | "retest_effort" | "variant_ratio" | "maturity";

export interface ReportItemFilter {
  types?: string[];
  states?: string[];
  q?: string | null;
  fields?: Record<string, string>;
  owner?: string | null;
  suspect?: boolean | null;
  variant?: string | null;
}

export interface ReportWidget {
  id: string;
  type: WidgetType;
  title?: string;
  width?: number;
  filter?: ReportItemFilter;
  metric?: "count" | "percent";
  percent_of?: ReportItemFilter | null;
  target?: number | null;
  group_by?: string;
  stack_by?: string | null;
  chart?: "bar" | "horizontal" | "donut" | "pie";
  columns?: string[];
  limit?: number;
  sort?: string;
  interval?: "week" | "month";
  periods?: number;
  series?: ("created" | "released" | "changed")[];
  cumulative?: boolean;
  coverage_type?: string | null;
  rows?: string | null;
  cols?: string | null;
  text?: string;
  change_types?: string[];
  variant?: string | null;
}

export interface ReportSummary {
  id: string;
  title: string;
  description: string | null;
  visibility: "project" | "private";
  template: string | null;
  owner: UserRef | null;
  mine: boolean;
  created_at: string;
  updated_at: string;
  widget_count: number;
}

export interface Report extends ReportSummary {
  widgets: ReportWidget[];
}

export interface ReportTemplate {
  key: string;
  title: string;
  description: string;
  widgets: number;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WidgetData = { ok: boolean; error?: string } & Record<string, any>;

export interface ReqifImportResult {
  dry_run: boolean;
  applied: boolean;
  title: string | null;
  analysis: {
    types: { name: string; count: number; suggested: string | null; mapped: string | null;
      attributes: { title: string[]; description: string[]; id: string[]; fields: Record<string, string>; unmapped: string[] } }[];
    relations: { name: string; count: number; suggested: string | null; mapped: string | null }[];
    specifications: { name: string; top_level: number }[];
    objects: number;
  };
  summary: Record<string, number>;
  warnings: string[];
  errors: string[];
}

// --- live documents: snapshots, history, compare, round trip, collections ------------------------

export interface DocNode {
  item_id: string;
  key: string;
  type_key: string;
  type_label: string;
  title: string;
  display_title: string;
  number: string | null;
  description: string;
  raw_description: string;
  content_hash: string;
  fields: { label: string; value: string }[];
  fields_raw: Record<string, unknown>;
  applicability: string | null;
  state: string | null;
  state_key: string | null;
  state_color: string | null;
  state_category: string | null;
  frozen: boolean;
  released: boolean;
  version: string;
  version_no: number;
  is_heading: boolean;
  link_id: string | null;
  position: number | null;
  comment_count: number;
  reused_in: number;
  suspect_links: number;
  links: { label: string; key: string; title: string }[];
  children: DocNode[];
}

export interface DocSnapshot {
  project_key: string;
  mode: "live" | "at" | "baseline";
  source: string;
  at: string | null;
  baseline: { id: string; name: string; created_at: string } | null;
  variant: { key: string; title: string; selection: string[] } | null;
  generated_at: string;
  root: DocNode;
}

export interface DocHistory {
  document: string;
  created_at: string;
  entries: { id: number; ts: string; actor: string; action: string; summary: string; items: string[] }[];
  baselines: { id: string; name: string; created_at: string; revision_rule: string; scope_is_document: boolean }[];
}

export interface DocStateRef {
  project?: string | null;
  document: string;
  at?: string | null;
  baseline?: string | null;
  variant?: string | null;
}

export interface CompareNode {
  item_id: string;
  key: string;
  type_key: string;
  type_label: string;
  title: string;
  display_title: string;
  number: string | null;
  description: string;
  state: string | null;
  version: string;
  applicability: string | null;
  is_heading: boolean;
  fields: { label: string; value: string }[];
}

export interface CompareResult {
  left: { project: string; document: string; title: string; source: string; mode: string; version: string };
  right: { project: string; document: string; title: string; source: string; mode: string; version: string };
  summary: Record<"added" | "removed" | "changed" | "moved" | "unchanged", number>;
  rows: {
    status: "added" | "removed" | "changed" | "moved" | "unchanged";
    left: CompareNode | null;
    right: CompareNode | null;
    moved: boolean;
    changes: { field: string; old: unknown; new: unknown; diff?: { op: "equal" | "insert" | "delete"; text: string }[]; html_diff?: string }[];
  }[];
}

export interface WordImportResult {
  dry_run: boolean;
  applied: boolean;
  summary: Record<string, number>;
  items: { key?: string; title?: string; status: string; base_version?: string; current_version?: string; new_version?: string;
    conflicts?: string[]; error?: string; changes?: { field: string; old: string; new: string }[] }[];
  comments: { item: string; author: string; text: string; reply: boolean }[];
}

export interface CommentThread {
  id: string;
  item_key: string | null;
  author: UserRef | null;
  external_author: string | null;
  source: string;
  body: string;
  created_at: string;
  resolved: boolean;
  resolved_at: string | null;
  resolved_by: UserRef | null;
  document_key: string | null;
  replies: CommentThread[];
}

export interface DocCollection {
  id: string;
  name: string;
  description: string | null;
  status: "open" | "closed";
  created_at: string;
  created_by: UserRef | null;
  closed_at: string | null;
  closed_by: UserRef | null;
  entries: { id: string; document: string; title: string; baseline_id: string; baseline: string; baseline_created_at: string }[];
}

export interface RecycledItem {
  key: string;
  type_key: string;
  title: string;
  version: string;
  deleted_at: string;
  deleted_by: string | null;
}

// --- engineering backbone ---------------------------------------------------------------------------------

export interface AppNotification {
  id: string; kind: "watch" | "owner" | "approval" | "mention" | "digest"; title: string; body: string | null;
  item_key: string | null; project: string | null; actor: string | null; created_at: string; read: boolean;
}
export interface NotificationList { unread: number; items: AppNotification[]; email: boolean; email_notifications: boolean }

export interface SavedQuery {
  id: string; name: string; shared: boolean; owner: UserRef | null; updated_at: string; count: number | null; can_edit: boolean;
  query: Record<string, unknown>;
}

export interface RiskRow {
  key: string; title: string; state: string | null; state_label: string | null; state_category: string | null;
  state_color: string | null; severity: number | null; occurrence: number | null; detection: number | null;
  rpn: number | null; level: string | null; severity_after: number | null; occurrence_after: number | null;
  detection_after: number | null; rpn_after: number | null; residual_level: string | null; failure_mode: string | null;
  mitigations: number;
}
export interface RiskOverview {
  enabled: boolean; type?: string; type_label?: string; scale?: number; matrix?: number[][]; residual_matrix?: number[][];
  risks?: RiskRow[];
  summary?: { total: number; high: number; medium: number; low: number; unrated: number; high_unmitigated: number;
    residual_high: number; accepted: number };
}

export interface BomRow {
  level: number; path: string; key: string; project: string; type: string; type_label: string; title: string;
  revision: string; version: string; state: string | null; state_category: string | null; quantity: number | null;
  unit: string | null; find_number: string | null; effective_from: string | null; effective_to: string | null;
  total_quantity: number; link_id: string; part_number: string | null; supplier: string | null; has_children: boolean;
}
export interface Bom { root: { key: string; title: string; version: string }; effective: string | null; rows: BomRow[];
  leaf_totals: { key: string; total_quantity: number }[] }
export interface WhereUsed { item: string; used_in: number; direct_parents: string[];
  paths: { key: string; title: string; project: string; version: string; quantity: number | null; find_number: string | null }[][] }

export interface PlanSummary {
  key: string; title: string; kind: "release" | "iteration" | "milestone"; state: string | null; state_label: string | null;
  state_color: string | null; start_date: string | null; due_date: string | null; goal: string | null; total: number;
  done: number; progress: number; expected: number | null; status: "on_track" | "at_risk" | "overdue" | "done";
  by_category: Record<string, number>; estimate: number; estimate_done: number; capacity: number | null;
  load: number | null; parent: string | null; children: string[];
}
export interface PlanItem {
  key: string; title: string; type_key: string; type_label: string; state: string | null; state_category: string | null;
  state_color: string | null; version: string; owner: UserRef | null; done: boolean; estimate: number | null; plan: string;
}
export interface PlanDetail extends PlanSummary {
  items: PlanItem[];
  child_plans: PlanSummary[];
  burnup: { date: string; done: number; scope: number; remaining: number; done_estimate: number; scope_estimate: number;
    remaining_estimate: number; future: boolean }[];
}
export interface Plans {
  enabled: boolean; type?: string; type_label?: string; releases: PlanSummary[]; plannable_types?: string[];
  estimate_field?: string; hierarchy?: boolean;
}

export interface Condition { field: string; op: "in" | "contains" | "between" | "exists" | "is"; values: unknown[]; not?: boolean }
export interface QueryState { q: string; conditions: Condition[] }

export interface BulkResult {
  dry_run: boolean; action: string; total: number; summary: Record<string, number>;
  results: { key: string; title: string; status: "ok" | "unchanged" | "skipped"; message: string | null }[];
}

export interface BoardConfig {
  types: string[]; q?: string | null; conditions: Condition[]; columns_by: string; swimlanes_by: string | null;
  hidden_columns: string[]; column_order: string[]; wip: Record<string, number>; card_fields: string[];
}
export interface Board { id: string; name: string; shared: boolean; config: BoardConfig; owner: UserRef | null; updated_at: string; can_edit: boolean }

export interface TimelineRow {
  key: string; title: string; type_key: string; kind: "release" | "iteration" | "milestone" | "task";
  start_date: string | null; due_date: string | null; progress: number; state: string | null; state_label: string | null;
  state_category: string | null; color: string | null; frozen: boolean; owner: UserRef | null; parent: string | null;
  depends_on: string[]; slack?: number; critical: boolean; baseline: { start_date: string | null; due_date: string | null } | null;
}
export interface Timeline {
  enabled: boolean; rows: TimelineRow[]; conflicts: { item: string; depends_on: string; message: string }[]; today: string;
  range: [string | null, string | null]; task_type: string | null; release_type: string; dependency_link: string | null;
}

export interface TemplateUpdates {
  template: string; available: boolean; template_version?: number; count: number;
  item_types: { key: string; label: string; prefix: string }[];
  fields: { type: string; key: string; label: string; field_type: string }[];
  link_types: { key: string; label: string }[];
  link_attributes: { link: string; key: string; label: string }[];
  link_endpoints: { link: string; sources: string[]; targets: string[] }[];
  workflows: { key: string; label: string }[];
  skipped: string[];
}

export interface DocTemplateInfo {
  id: string; name: string; filename: string; size: number; placeholders: string[]; unknown: string[];
  has_content: boolean; has_toc: boolean; created_by: UserRef | null; created_at: string;
}
