# 7 Configuration guide: tailoring Ariadne per customer

A customer's information model is a **process template** — a YAML file in
`backend/almlight/modules/projects/templates/`. New projects copy it; existing projects can change their copy via
*Settings → Information model → Edit as JSON* (managers) or `PUT /api/v1/projects/{key}/config`.

## 7.1 Workflow for a customer engagement

1. Start from `systems-engineering.yaml` (full model) or `lean-requirements.yaml` (requirements & tests only).
2. Copy it to `templates/<customer>.yaml`, give it a new `key` and `label`. Keep customer templates in a private
   repository or deployment overlay — not in this public repository.
3. Rename labels to the customer's language (keys stay technical, labels are what users see).
4. Remove types the customer does not need, add fields they track, adjust workflows and approval rules.
5. If you rename engine-relevant keys (e.g. `verifies`), point `semantics` at the new keys.
6. Validate: the server refuses invalid templates at start-up/project creation (`pytest tests/test_units.py`
   validates the shipped ones).

## 7.2 Reference

```yaml
key: acme_se                 # [a-z][a-z0-9_]*
label: ACME Systems Engineering
revision_scheme: letters     # letters (A, B, …) | numbers (1, 2, …)

item_types:
  - key: system_requirement
    label: Systemanforderung   # any language
    prefix: SYS                # key prefix: SYS-1, SYS-2 …  (unique, uppercase)
    category: requirement      # requirement | architecture | verification | change | document | variability | other
    workflow: requirement      # optional; no workflow = no lifecycle
    change_controlled: true    # revisions only under an open change order
    document: false            # true = can act as a live document (specification)
    fields:
      - {key: priority, label: Priority, type: enum, options: [must, should, could], default: should}
      - {key: asil, label: ASIL, type: enum, options: [QM, A, B, C, D]}
      - {key: rationale, label: Rationale, type: text}
      - {key: drawing_no, label: Drawing no., type: string, pattern: "^D-[0-9]{6}$"}
      - {key: weight_g, label: Weight [g], type: number, min: 0, max: 50000}     # bounds checked by the API
      - {key: effort_total, label: Effort, type: number, formula: "effort_design + effort_test"}  # computed
      - key: criticality                                                       # computed enum from bands
        label: Criticality
        type: enum
        options: [{key: low, label: Low}, {key: high, label: High}]
        classify: {field: effort_total, bands: [[0, low], [40, high]]}
      # types: string, text, integer, number, boolean, date, enum, multienum, tags, user, url, steps
      # steps = ordered list of {step, expected} (test steps); formula: + - * / // % ( ), min, max, abs, round

link_types:
  - key: verifies
    label: verifies
    reverse_label: verified by
    sources: [test_case]
    targets: [system_requirement]   # "*" = any type
    suspect_on_target_change: true  # changes of the target flag the link
    structural: false               # true = ordered hierarchy (documents, structures, feature tree)
    acyclic: false
    editable_on_frozen_source: false
    attributes:
      - {key: quantity, label: Quantity, type: integer}

workflows:
  - key: requirement
    label: Requirement lifecycle
    states:
      - {key: draft, label: Draft, category: draft, initial: true}
      - {key: in_review, label: In Review, category: review, frozen: true}
      - {key: approved, label: Approved, category: released, frozen: true, released: true}
    transitions:
      - {key: submit, label: Submit for review, from: [draft], to: in_review}
      - key: approve
        label: Approve
        from: [in_review]
        to: approved
        min_role: contributor          # who may trigger
        comment_required: false
        signature: false               # direct e-signature by the actor
        approval:                      # or: an approval by others
          roles: [reviewer]
          count: 2
          signature: true
          allow_self_approval: false   # four-eyes principle
          reject_to: draft
        guards: []                     # see 7.3
        effects: []                    # see 7.3

semantics:                             # only needed when keys differ from the defaults
  affects_link: affects
  verifies_link: verifies
  satisfies_link: satisfies
  derives_link: derives_from
  requires_link: requires
  excludes_link: excludes
  test_case_types: [test_case]
  test_run_type: test_run
  stakeholder_types: [stakeholder_requirement]
  element_types: [system_element]
  test_steps_field: test_steps         # steps field of test cases (step-wise execution)
  defect_type: problem_report          # created by "Defect" in a test execution
  risk_type: risk                      # Risks page (fields severity, occurrence, detection, rpn, risk_level, …_after)
  mitigation_link: mitigated_by        # risk -> requirement/element/test
  release_type: release                # Plans page (fields start_date, due_date, goal)
  planned_link: planned_in             # item -> release (set editable_on_frozen_source: true)
```

Engine features appear only when their bindings exist in the model: without a `risk` type there is no Risks page,
without `release` and `planned_in` no Plans page. BOM columns come from the attributes `quantity`, `unit`,
`find_number`, `effective_from` and `effective_to` of the structural link.

State categories: `draft`, `review`, `released`, `obsolete`, `open`, `in_progress`, `closed`. Flags:
`frozen` locks content and owned links; `released` marks the released version and enables *Revise*;
`implementation_open` (change orders) allows revising affected items under it.

## 7.3 Guards and effects

| Guard | Blocks until |
|---|---|
| `contained_items_released` | all items below this item (structural links) are released or obsolete |
| `has_affected_items` | at least one `affects` link exists |
| `affected_items_revised` | every affected item with action `revise` has a revision under this change order; `add` items are new |
| `all_records_executed` | the test run has records and none is `not_run` |

| Effect | Does |
|---|---|
| `release_affected_items` | moves affected items to their released state (action revise/add) or obsolete state (action obsolete) |

## 7.4 Conventions the engine relies on

- Features: item types in category `variability` with a `code` field; variants: same category with a `selection`
  (tags) field; feature tree via a structural link type.
- Structure views use the structural link type(s) and the `level` field of element types (product root = `level: product`).
- Test runs may have a `variant` field (variant key) for variant-specific verification status.

## 7.5 Changing the model of a live project

The server checks compatibility before accepting a new configuration:

- item types, link types and states that are in use cannot be removed;
- prefixes of item types in use cannot change;
- new fields, types, states, transitions and link types can be added at any time;
- removed fields disappear from the UI; old values remain in the version history.

Each accepted change increments the project's configuration version and is audited.

**Template updates.** When the shipped template gains new item types, fields, link types, link attributes or
workflows, *Settings → Information model* lists them for existing projects; a manager takes them over in one step.
Only additions are applied — the project's own changes are never overwritten — and the result passes the same
compatibility check as any model change (API: `GET`/`POST /projects/{k}/template-updates`).
