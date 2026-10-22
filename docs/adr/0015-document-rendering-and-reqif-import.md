# ADR-0015 Document rendering (Word/PDF) and ReqIF import identity

**Context.** Customers and auditors expect specifications as Word/PDF documents, ideally exactly as released. OEMs and
suppliers exchange requirements as ReqIF and send updated files repeatedly.

**Decision.**
- *Rendering*: a document snapshot (ordered tree of item contents) is built either from the live state or from a
  **baseline** (versions and links frozen in the baseline). Word is generated with python-docx (title table, TOC field,
  headings, requirement blocks, field tables, traces), PDF with ReportLab Platypus (title page, TOC with page numbers,
  running header/footer, Unicode DejaVu fonts installed in the image). Both render Markdown through one parser
  (markdown-it-py). All libraries are permissively licensed and pure-Python apart from wheels.
- *ReqIF import*: a dry-run analysis suggests the mapping of SPEC-OBJECT-TYPEs to item types (by name), attributes to
  title/description/fields (well-known ReqIF names such as `ReqIF.Text`, `ReqIF.ChapterName`, field labels, enum
  labels) and relation types to link types; the user adjusts and applies. DOORS-style headings (chapter name without
  text) become heading items. Each imported object stores its ReqIF identifier as an external reference; objects that
  this installation exported carry deterministic identifiers that map back to their items. Re-imports therefore update
  instead of duplicating; frozen items are reported, not changed. Imports are all-or-nothing on errors; link problems
  are warnings.

**Consequences.** + Released documents can be reproduced at any time from a baseline. + Round trips with customers
work without manual key matching. − Word's table of contents is filled when the document is opened (field update);
rich ReqIF content beyond paragraphs, emphasis, lists and tables (e.g. embedded OLE objects) becomes placeholders.
