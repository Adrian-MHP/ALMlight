# 20 Architecture modelling: diagrams over the model (0.10)

Until now the architecture lived in Ariadne as *items and links* — elements, functions, interfaces, with
`contains`, `realizes`, `connects`, `satisfies` — shown as a tree on the Structure page and as a matrix on the
Traceability page. What was missing is the thing every architecture tool is bought for: **a picture you can lay
out, and that stays connected to the model**.

## 20.1 What the established tools deliver, and what Ariadne needed

| Capability | Enterprise Architect (Sparx) | Cameo / MagicDraw (SysML) | ArchiMate tools | Ariadne before | Ariadne now |
|---|---|---|---|---|---|
| A metamodel: typed elements and relationships with rules | UML/SysML profiles | SysML v1/v2 | ArchiMate layers and relationship table | **yes** — item types and link types per project template | unchanged |
| Repository browser, properties, search | yes | yes | yes | yes (Items, Structure, queries) | unchanged |
| **Diagrams with layout** | core | core | core | **no** | **yes** |
| **An element lives in the model, a diagram only shows it** | yes (delete from diagram ≠ from model) | yes | yes | – | **yes** |
| Diagram kinds / viewpoints | ~15 diagram types | BDD, IBD, activity, state, use case … | ArchiMate viewpoints | – | **6 viewpoints** (suggestions, not restrictions) |
| Relationship validity rules | profile-driven | strict | the ArchiMate matrix | yes (link type `sources`/`targets`) | enforced while drawing |
| Traceability to requirements and tests | add-ins | yes | weak | **yes** (typed links, coverage, impact) | a drawn relationship *is* that link |
| Versioning, baselines, approval of a diagram | external version control | Teamwork Cloud | varies | – | a diagram is a normal item: versions, revisions, workflow, baselines |
| Export | XMI, images, documents | XMI, images | Open Exchange, images | EA XMI, SysML v2 (model) | **+ SVG per diagram** |
| Free-form drawing (shapes, pictures) | yes | yes | yes | – | only notes — deliberately |
| Code generation, simulation, executable models | yes | yes (fUML) | – | – | **out of scope** |

Two conclusions shaped what was built. First, Ariadne already has the hard part — a configurable, rule-checked
metamodel with traceability — so a second notation (importing all of ArchiMate or UML) would duplicate it and
split the data. The project's **own item types are the element types**, and their category gives the colour.
Second, what makes a tool a *modelling* tool and not a drawing tool is one rule: the model owns the elements,
a diagram only shows them. That rule is the centre of this feature.

What is deliberately **not** here: free drawing of arbitrary shapes, swimlanes and layout decoration, behaviour
diagrams (activity, state machine, sequence), code generation and simulation. For behaviour and for exchange
with the specialist tools, the [connectors](17-code-and-connectors.md) remain the way: import from Enterprise
Architect or a SysML v2 server, keep working in Ariadne, export EA XMI.

## 20.2 How it works

A diagram is an item of type **Architecture Diagram** (`DIA-…`), so everything that holds for items holds for it:
it has versions and a change history, it goes through a workflow, it can be released, baselined, compared and put
into a document, and the permissions are the project roles.

Its content is the canvas:

- **Nodes** show items of the project — one item may be on many diagrams. A node is a reference, not a link, so
  putting something on a diagram creates no traceability and changes no data.
- **Edges** *are* links of the project. Drawing one creates a real typed link with all the model's rules (a test
  case cannot `satisfy` a requirement), and it shows up in the matrix, in coverage and in the impact analysis.
  When two elements that are already linked meet on a canvas, the link is drawn by itself. An edge that stands
  for no link cannot be stored — this is the rule the canvas is checked against. Editing a link's attributes
  writes a new link row with a new id (that is how versioned links work); the diagram follows it by the
  relationship it shows, so the edge survives.
- **Notes** are plain text on the canvas, nothing else.

That gives the distinction people expect from a modelling tool:

| Action | Effect on the diagram | Effect on the project |
|---|---|---|
| *Remove from diagram* (element) | gone from this view | nothing — the item and its links stay |
| *Remove from diagram* (relationship) | gone from this view | nothing — the link stays |
| *Delete the link as well* | gone | the link is deleted (audited) |
| Delete the item (on the item page) | shown as a red placeholder, and the diagram says so | the item is in the recycle bin |

## 20.3 Working with it

*Architecture* in the navigation lists the diagrams. In a diagram:

- **Add element** puts any item of the project on the canvas, or picks from *linked to what the diagram already
  shows* — the quick way to grow a view along the existing traceability.
- **Draw relationship**: select an element, press the button, click the second element; Ariadne offers exactly the
  relationship types the information model allows between those two types.
- **Arrange** lays the canvas out in layers: whatever points at something else stands above it (containment,
  derivation). Cycles are broken rather than looping.
- Drag to move, drag the background to pan, the wheel or the buttons to zoom. A diagram that is wider than the
  window is fitted into it when opened, and *Show all* goes back to that view. **Save** stores the places — layout
  is saved explicitly so that moving a box does not produce a version for every pixel, while adding, connecting
  and removing are immediate and audited. Places that were moved but not saved survive a refresh of the data.
- The side panel shows what the selected element is, its state and version, its relationships, and the way to its
  item page.
- **Download as SVG** gives the picture; the same rendering is available at
  `GET /projects/{k}/diagrams/{key}.svg` for reports and wikis.

**Viewpoints** (system context, decomposition, internal structure and interfaces, requirements allocation,
physical/deployment, free) decide which element and relationship types are *suggested*. They never restrict what
you may draw — a project's own model is the authority.

The demo project carries three diagrams to look at: *Pressure transmitter — decomposition* (the product and its
subsystems and modules), *Signal chain — internal structure* (the measuring cell, the board and the interface
between them) and *Requirements allocation — measuring chain* (which element satisfies which requirement, and
where that requirement comes from).

## 20.4 What a canvas is not

A canvas is a picture, not a field value. It is therefore not a column in the CSV and Excel exports, not a
filter in the query builder, and not a value in the item list; the version history, the baseline and the
document comparison say how much a diagram shows ("10 elements, 9 relationships") instead of printing its
coordinates, and the assistant is told the same. The picture itself comes from the SVG endpoint.

## 20.5 Limits

- One canvas, straight (and for parallel relationships, slightly bowed) connections: no manual bend points, no
  routing around boxes, no swimlanes, no nesting of elements inside elements.
- No behaviour diagrams (activity, state machine, sequence) and no code generation.
- A diagram is rendered into Word and PDF exports as a link, not yet as an embedded picture; the SVG endpoint is
  there, embedding it in the document renderers is the next step.
- Up to 300 elements and 600 relationships per diagram — beyond that, split the view.
- The canvas is saved as a whole: two people editing the same diagram at the same time get a clean conflict
  (409) from the version check, not a merge.
