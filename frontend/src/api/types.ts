// Types mirroring the ALMlight REST API (see /api/v1/docs).

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
  | "string" | "text" | "integer" | "number" | "boolean" | "date" | "enum" | "multienum" | "tags" | "user" | "url";

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
}

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

export type ItemCategory = "requirement" | "architecture" | "verification" | "change" | "document" | "variability" | "other";

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
  verifies_link: string;
  satisfies_link: string;
  derives_link: string;
  requires_link: string;
  excludes_link: string;
  test_case_types: string[];
  test_run_type: string | null;
  stakeholder_types: string[];
  element_types: string[];
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
}

export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  uploaded_by?: string | null;
  uploaded_at?: string | null;
}

export interface ItemDetail extends Item {
  description: string;
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
