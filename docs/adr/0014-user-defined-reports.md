# ADR-0014 User-defined reports as widget lists evaluated on the server

**Context.** Enterprise ALM tools let end users build their own reports (e.g. Polarion LiveReports). Steering boards
need platform KPIs (reuse, change lead time, re-test effort, variant economics) that are not simple item counts.
SMEs should not need a separate BI tool, yet BI tools must be able to pull the numbers.

**Decision.** A report is a project-scoped record with a title, a visibility (shared with the project or private) and
an ordered list of **widgets** stored as JSON and validated by a Pydantic schema. Widget types: KPI number
(count/percentage with target), chart (group by state/type/category/owner/field, optional split), table (chosen
columns), trend (created/released/changed per week or month, optionally cumulative), coverage, traceability matrix,
maturity, text, and four engineering KPIs computed in `reports/kpis.py`. All widgets are **evaluated on the server**
with the same item filters as the item list; a failing widget returns its own error and never breaks the report.
The editor previews unsaved widgets through `POST /reports/preview-widget`. Reports export to Excel (one sheet per
widget) and print to PDF from the browser; templates give users a starting point. The KPIs are also available as
plain JSON (`/kpis/{name}`) for BI tools.

**Consequences.** + End users compose reports without code; one evaluation path for UI, Excel and API.
+ Widgets degrade gracefully across information models. − Evaluation loads matching items into memory
(fine for SME volumes up to tens of thousands of items); heavier aggregation can move to SQL per widget type later.
