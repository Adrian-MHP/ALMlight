# 15 Work management: queries, bulk edit, boards, plans, timeline, time and resources (0.6 – 0.7)

Version 0.6 brought the daily work-management tools users know from Polarion (query builder, table configuration,
bulk edit, boards, plans) and Teamcenter Schedule Manager (Gantt timeline with dependencies, critical path and
baseline comparison). Version 0.7 completes them: boolean queries across fields, all four dependency types with lag,
auto-scheduling, time recording with a weekly timesheet, resource load and levelling. Everything works on the same
items, links and workflows as the rest of Ariadne — a card moved on a board, a bar dragged on the timeline or a task
moved by levelling is an ordinary, audited change.

| Feature | Where | What it gives users |
|---|---|---|
| [Query builder](#151-query-builder-and-query-language) | Items | Field chips with value pickers, *is / is not*, OR/AND groups across fields, a query text to copy, paste and edit |
| [Table](#152-configurable-table-and-preview) | Items | Column chooser incl. custom fields, sort by any column, split preview, saved views with columns |
| [Bulk edit](#153-bulk-edit) | Items | Select rows or the whole result; edit fields/owner, change status, plan, link, watch, delete — with a preview |
| [Boards](#154-kanban-boards) | Planning → Boards, Changes | Kanban over any items; columns and swimlanes by status, owner, plan, type or a field; WIP limits; drag & drop runs the transition |
| [Plans](#155-plans-iterations-capacity-and-the-planning-board) | Planning → Plans | Release → iteration / milestone hierarchy, estimates vs. capacity, burn-up and burn-down, planning board |
| [Timeline](#156-timeline-gantt) | Planning → Timeline | Gantt of plans, tasks and milestones; four dependency types with lag, critical path, conflicts, baseline comparison, drag to reschedule, auto-schedule |
| [Time recording](#157-time-recording-and-the-timesheet) | Item → Time, Planning → Timesheet | Hours per item and day, spent and remaining effort, a weekly timesheet |
| [Resources](#158-resource-load-and-levelling) | Planning → Timeline → Resources | Load per person and week against capacity, overloads, resource levelling with preview |
| [Workflow viewer](#159-workflow-viewer) | Item overview, preview | State diagram with the current state, the path taken and the transitions possible now |

## 15.1 Query builder and query language

The filter bar of the item list works like Polarion's query bar:

- **Search** for key, title and text, plus **chips** for conditions. *Filter* adds a field: type, status, status
  category, owner, created/updated (dates and periods such as *last 30 days*), created by, title, text, key, revision,
  flags (released, frozen, suspect links, watched by me, checked-out files, has files), *planned in*, every link type
  in both directions (*verified by: none* finds the verification gap), and **every custom field** of the selected
  types — enums and users with checkbox lists, numbers with ranges, dates with periods, text with words.
- Each chip can be negated (*is not*); a negated chip includes items without a value, as in Polarion.
- **OR across fields**: *OR …* in a chip's editor adds an alternative on another field and turns the chip into a
  **group** — e.g. *(Priority: Must OR Owner: Nobody)*. A group combines its members with *any* (OR) or *all* (AND),
  can be excluded as a whole (*NOT (…)*), can hold further groups, and can be split back into separate chips.
- **Query text** (the `</>` button) shows the same query as text — copy it into a mail or paste one and *Apply*:

```
type:system_requirement (priority:must OR NOT link.verifies.in:*) NOT (owner:none OR safety_relevant:true)
```

Rules: clauses are combined with AND (`AND` optional); `OR` combines clauses (or values inside `field:(a OR b)`);
parentheses group; `NOT` or a leading `-` negates a clause or a group; `field:*` means "has a value";
`[a TO b]` is a range with `*` for open ends; dates accept `YYYY-MM-DD`, `today`, `-7d`, `+2w`, `-3m`; user fields
accept user names, `me` and `none`; custom fields are written by their key (`field.<key>` if the key collides with a
built-in name); links as `link.<type>.out` / `link.<type>.in`; words without a field are free text (inside an OR
branch they search the text of that branch). Mistakes are explained ("OR needs a condition on both sides …").

The query is part of the URL (bookmarkable, shareable) and is what *Export*, saved views, boards and bulk edit use.
In the API, a group is `{"or": [...]}` or `{"and": [...]}` with an optional `"not": true`, nested up to 8 levels.

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

- **Cards**: any items selected by types and a filter (the same query builder, groups included).
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

- **Dependencies** (`depends on`) in the four types of Teamcenter Schedule Manager and MS Project, each with a **lag**
  in working days (negative = lead):

  | Type | Meaning | Rule (dates are inclusive working days) |
  |---|---|---|
  | FS — finish-to-start (default) | starts after the predecessor finishes | start later than predecessor finish + lag |
  | SS — start-to-start | starts when the predecessor starts | start no earlier than predecessor start + lag |
  | FF — finish-to-finish | finishes when the predecessor finishes | finish no earlier than predecessor finish + lag |
  | SF — start-to-finish | finishes when the predecessor starts | finish no earlier than the working day before the predecessor's start + lag |

  Arrows leave and enter the matching bar ends; non-default types and lags are labelled (e.g. *SS +3d*). A row's menu
  → *Dependencies…* lists the predecessors of the item, changes their type and lag, removes them, and adds new ones.
- **Critical path**: total slack in working days is calculated against successors (per dependency type and lag) and
  the deadline of the plan a task belongs to; items without slack are shown in red. **Conflicts** — any violated
  dependency, a milestone before its predecessors — are listed with the rule that is broken and drawn dashed.
- **Auto-schedule** (toolbar): a forward pass along the dependencies, with a **preview** of every move before
  anything is saved. *Resolve conflicts* only moves successors later where a dependency is violated; *As soon as
  possible* also pulls dependent work in to the earliest date its predecessors allow. Tasks and milestones move by
  working days and keep their duration; plans (releases, iterations), frozen, started and finished items keep their
  dates — conflicts they cause are listed with the reason. The run can be limited to one plan and its sub-plans.
- **Baseline comparison**: choose a baseline and every bar shows its baselined dates as a grey bar below it.
- **Rescheduling**: drag a bar to move it, drag its ends to change start or finish, drag a milestone to move its
  date — saved immediately as an ordinary item change (frozen items cannot be moved).
- Zoom weeks / months / quarters; today line; the view opens around today.

## 15.7 Time recording and the timesheet

- **Time tab** on every task and on every item with an estimate: *Estimate*, *Spent* (all recorded hours) and
  *Remaining* (estimate − spent; 0 once the item is finished), a progress bar that turns red when the estimate is
  exceeded, and a form to record hours on a day with a comment. Records can be changed or deleted by their author
  and by project managers.
- **Timesheet** (*Planning → Timesheet*): the user's week as a grid — one row per item worked on, plus the open tasks
  the user owns in that week; one column per day. Typing hours into a cell sets the hours of that item and day
  (0 clears it); totals per day and week and the share of the weekly capacity are shown. *Add row* adds any other
  item. Managers can open the (read-only) timesheet of any member.
- Rules: hours are actuals — today or earlier, at most 24 h per person and day; recording time does not create item
  versions, so frozen and released items can be booked on; every record is in the audit trail.
- **Privacy** (works-council friendly default): everybody sees the total spent on an item; individual records are
  visible to their author and to project managers only.

## 15.8 Resource load and levelling

*Planning → Timeline → Resources* shows a heatmap: one row per person, one column per week (8, 12 or 26 weeks).

- **Planned load** = the remaining work of open tasks (estimate − recorded time, in hours) owned by the person,
  spread evenly over the task's working days from today on; a task without an estimate counts as full-time; work of
  an overdue task lands on the next working day. **Capacity** = the member's *hours per day* in this project
  (*Settings → Members*, default 8) × 5. Cells are coloured by load (≤ 60 %, ≤ 90 %, ≤ 100 %, overloaded) and show the
  recorded hours of past weeks; a cell opens the list of tasks behind it. Tasks without an owner are shown as
  *Unassigned*.
- **Level resources**: greedy levelling as in Teamcenter/MS Project — tasks of overloaded people are delayed (never
  pulled in) by working days until the owner has room, keeping their duration and all dependencies (successors move
  along). Started, frozen and finished work is booked first and keeps its dates; earlier and less flexible tasks are
  placed first; a task needing more than a full day is placed where its owner has nothing else. The **preview**
  lists the moves and the overloads that remain; *Apply* saves each move as an ordinary item change. The run can be
  limited to one plan.

## 15.9 Workflow viewer

Every item with a workflow shows its **state diagram** on the overview (and in the preview): the current state
filled, states already passed outlined, the path taken drawn solid, and the transitions the current user can trigger
now highlighted.

## 15.10 Configuration

The shipped template (version 4) has the task type with its workflow, the release fields *kind* (release /
iteration / milestone) and *capacity*, the *estimate* field on plannable types, the link types `part_of` and
`depends_on`, and on `depends_on` the link attributes *dependency type* (`fs`, `ss`, `ff`, `sf`) and *lag* (working
days). Existing projects take them over under *Settings → Information model* (template updates; links created
before keep finish-to-start without lag). The bindings are configurable (`semantics`: `task_type`, `subplan_link`,
`dependency_link`, `dependency_type_attribute`, `dependency_lag_attribute`, `estimate_field`, `capacity_field`).
Hours per day are set per project member. Time records, the timesheet, resources and levelling need no
configuration; estimates of tasks are read as hours.
