# 15 Work management: queries, bulk edit, boards, plans and the timeline (0.6)

Version 0.6 brings the daily work-management tools users know from Polarion (query builder, table configuration,
bulk edit, boards, plans) and Teamcenter Schedule Manager (Gantt timeline with dependencies, critical path and
baseline comparison). Everything works on the same items, links and workflows as the rest of Ariadne — a card moved
on a board or a bar dragged on the timeline is an ordinary, audited change.

| Feature | Where | What it gives users |
|---|---|---|
| [Query builder](#151-query-builder-and-query-language) | Items | Field chips with value pickers, *is / is not*, Any/None, a query text to copy, paste and edit |
| [Table](#152-configurable-table-and-preview) | Items | Column chooser incl. custom fields, sort by any column, split preview, saved views with columns |
| [Bulk edit](#153-bulk-edit) | Items | Select rows or the whole result; edit fields/owner, change status, plan, link, watch, delete — with a preview |
| [Boards](#154-kanban-boards) | Planning → Boards, Changes | Kanban over any items; columns and swimlanes by status, owner, plan, type or a field; WIP limits; drag & drop runs the transition |
| [Plans](#155-plans-iterations-capacity-and-the-planning-board) | Planning → Plans | Release → iteration / milestone hierarchy, estimates vs. capacity, burn-up and burn-down, planning board |
| [Timeline](#156-timeline-gantt) | Planning → Timeline | Gantt of plans, tasks and milestones; dependencies, critical path, conflicts, baseline comparison, drag to reschedule |
| [Workflow viewer](#157-workflow-viewer) | Item overview, preview | State diagram with the current state, the path taken and the transitions possible now |

## 15.1 Query builder and query language

The filter bar of the item list works like Polarion's query bar:

- **Search** for key, title and text, plus **chips** for conditions. *Filter* adds a field: type, status, status
  category, owner, created/updated (dates and periods such as *last 30 days*), created by, title, text, key, revision,
  flags (released, frozen, suspect links, watched by me, checked-out files, has files), *planned in*, every link type
  in both directions (*verified by: none* finds the verification gap), and **every custom field** of the selected
  types — enums and users with checkbox lists, numbers with ranges, dates with periods, text with words.
- Each chip can be negated (*is not*); a negated chip includes items without a value, as in Polarion.
- **Query text** (the `</>` button) shows the same query as text — copy it into a mail or paste one and *Apply*:

```
type:system_requirement state:(draft OR in_review) priority:must NOT link.verifies.in:* updated:[-30d TO *]
```

Rules: clauses are combined with AND (`AND` optional); `OR` combines values inside parentheses; `NOT` or a leading
`-` negates; `field:*` means "has a value"; `[a TO b]` is a range with `*` for open ends; dates accept `YYYY-MM-DD`,
`today`, `-7d`, `+2w`, `-3m`; user fields accept user names, `me` and `none`; custom fields are written by their key
(`field.<key>` if the key collides with a built-in name); links as `link.<type>.out` / `link.<type>.in`; words
without a field are free text. Mistakes are explained ("OR combines values inside parentheses …").

The query is part of the URL (bookmarkable, shareable) and is what *Export* delivers.

## 15.2 Configurable table and preview

- **Columns**: key, title, type, status, version, owner, updated, created, created by, applicability and every custom
  field — chosen and ordered per item type (remembered per browser), and stored with a saved view.
- **Sorting** by clicking a column header, also by custom fields (numbers numerically).
- **Preview**: clicking a row opens the item beside the list (fields, text, links, workflow), the key opens the full
  page; the preview can be switched off.
- **Saved views** keep query, sort order and columns; personal or shared.

## 15.3 Bulk edit

Select rows (or *Select all N matching* for the whole query result, up to 1,000 items) and choose an action:

| Action | Effect |
|---|---|
| Edit fields | Set or clear one field, or the owner, on all selected items |
| Change status | Run a workflow transition (comment and e-signature once for all; approval transitions request an approval per item) |
| Plan / remove from a release | Plan into a release, iteration or milestone, optionally moving them from another plan |
| Link | Link all selected items to one item (any link type valid for all selected types) |
| Watch / stop watching | Follow the items |
| Move to recycle bin | Managers; released items are skipped |

Every action first shows a **preview** — per item *ok*, *unchanged* or *skipped* with the reason (frozen, field not
defined for the type, transition not possible from the current state, permission). *Apply* then changes only what the
preview showed as *ok*. Each item goes through the normal services, so versions, suspect links, audit entries and
notifications are produced exactly as for single edits (watchers receive one summary instead of many messages).

## 15.4 Kanban boards

*Planning → Boards* holds personal and shared boards; templates create common ones in one click.

- **Cards**: any items selected by types and a filter (the same query builder).
- **Columns** by status, owner, *planned in*, type, or an enum, user or yes/no field; **swimlanes** by another of
  these; hidden columns; **WIP limits** per column (the count turns red when exceeded); fields shown on cards.
- **Drag & drop** changes what the column or swimlane stands for: for status columns the matching workflow
  transition runs (a dialog asks for the comment or e-signature when the transition requires one; approval
  transitions request the approval). While dragging, columns without a possible transition are dimmed; dropping
  there explains why nothing happens. Owner, plan and field columns update the item. Computed fields (e.g. risk
  level) group cards but cannot be changed by moving them.
- Clicking a card opens its preview. The *Changes* page is a board of the change items by status.

## 15.5 Plans, iterations, capacity and the planning board

- Plans form a hierarchy: a **release** contains **iterations** (sprints) and **milestones** (`part of`). A plan's
  scope includes the work planned into its sub-plans, so a release shows the progress of all its sprints.
- **Estimates and capacity**: plannable items have an *Estimate* field, plans a *Capacity*. Each plan shows the
  planned estimate against its capacity (**load**, red above 100 %). Progress counts estimates when all planned items
  are estimated, otherwise items.
- **Burn-up and burn-down**, by items or by estimate, with the today line and the expected progress by today; status
  *on track*, *at risk*, *overdue*, *done*.
- **Planning board**: the **backlog** (unplanned items, searchable, filtered by type) beside the plan and its
  iterations; drag items from the backlog into an iteration, between iterations, or back to the backlog. Each column
  shows its load.

## 15.6 Timeline (Gantt)

*Planning → Timeline* shows releases (summary bars), iterations, milestones (diamonds) and **tasks** (work packages
with start, finish, progress and estimate) in a hierarchy: release → iterations and milestones → tasks planned into
them; unplanned tasks at the end.

- **Dependencies** (`depends on`, finish-to-start) are drawn as arrows; add them from a row's menu.
- **Critical path**: total slack in working days is calculated against successors and the deadline of the plan a
  task belongs to; items without slack are shown in red. **Conflicts** — a successor starting before its predecessor
  finishes, a milestone before its predecessors — are listed and drawn dashed.
- **Baseline comparison**: choose a baseline and every bar shows its baselined dates as a grey bar below it.
- **Rescheduling**: drag a bar to move it, drag its ends to change start or finish, drag a milestone to move its
  date — saved immediately as an ordinary item change (frozen items cannot be moved).
- Zoom weeks / months / quarters; today line; the view opens around today.

## 15.7 Workflow viewer

Every item with a workflow shows its **state diagram** on the overview (and in the preview): the current state
filled, states already passed outlined, the path taken drawn solid, and the transitions the current user can trigger
now highlighted.

## 15.8 Configuration

The shipped template (version 3) adds the task type with its workflow, the release fields *kind* (release / iteration
/ milestone) and *capacity*, the *estimate* field on plannable types and the link types `part_of` and `depends_on`.
Existing projects take them over under *Settings → Information model* (template updates). The bindings are
configurable (`semantics`: `task_type`, `subplan_link`, `dependency_link`, `estimate_field`, `capacity_field`).
