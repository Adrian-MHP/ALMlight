# ADR-0035 Architecture diagrams are views over the project's own model, not a second notation

**Context.** The engineering backbone carried architecture only as items and links (elements, functions,
interfaces with `contains`, `realizes`, `connects`, `satisfies`) shown as a tree and a matrix. What customers
expect from Enterprise Architect, Cameo or an ArchiMate tool is a diagram they can lay out. Two ways were open:
bring in an established notation (ArchiMate's ~60 element types and its relationship table, or a UML/SysML
profile) with its own repository, or draw the project's existing model. The first duplicates the metamodel
Ariadne already has — item types and link types are configured per customer template and already carry the
validity rules, the traceability, the versioning and the permissions — and would split the data into "the ALM
items" and "the architecture model", which is exactly the gap this product exists to close.

**Decision.** A diagram is an **item** of type `diagram` whose `content` field (a new, strictly validated field
type) holds nodes and edges with their places. The project's **own item types are the element types** and their
category gives the colour; **an edge is a link of the project**, created through the normal link service with
its rules, its suspect marking and its audit entry, while a **node is only a reference** — an element can appear
on many diagrams and taking it off one changes nothing in the model. Viewpoints (context, decomposition,
internal, allocation, deployment, free) *suggest* types, they do not restrict them. Layout is saved explicitly,
structural changes immediately. The same picture is rendered server-side as SVG. Free-form drawing, behaviour
diagrams, code generation and simulation stay out; exchange with the specialist tools remains the job of the
connectors (EA XMI, SysML v2).

**Consequences.** + A diagram inherits versions, revisions, workflow, baselines, comparison, permissions and
export from the item model, with no second storage and no synchronisation; what an architect draws is
immediately traceability that coverage, impact and the matrix see. + Every customer template gets diagrams of
*its own* model without any mapping. − No standard notation: a diagram is not ArchiMate or SysML and cannot be
exchanged as such (the connectors cover that direction), and the shapes are boxes, not stereotyped symbols. −
The canvas is one JSON value in the item, so two people editing one diagram get a conflict instead of a merge,
and very large diagrams have to be split.
