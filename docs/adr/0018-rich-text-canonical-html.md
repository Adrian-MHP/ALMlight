# ADR-0018 Rich text as canonical HTML with one content model

**Context.** Item texts were Markdown. Users expect a rich-text editor with tables and images (as in enterprise ALM
tools), and texts travel through many formats: the editor, the REST API, Word export and round trip, PDF, ReqIF
(XHTML), Excel and archives. Each format pair converting directly would drift apart, and differently serialised but
equal texts would create false versions and diffs.

**Decision.** Texts are stored as *canonical HTML*: a small, safe subset written by exactly one serialiser. Every input
(editor HTML, Markdown/plain text from the API, ReqIF XHTML, Word content, the co-editing document) is parsed into one
block model (`core/richtext.py`) and written back canonically; every output (HTML, Word, PDF, XHTML, Markdown, plain
text) renders from the same model (`io/rich_render.py`). Canonical form fixes mark nesting, block wrapping (list items
and table cells contain paragraphs, like the editor's schema), table structure and attribute sets. Images are not
embedded: they live in the content-addressed file store, are registered per project and referenced as
`/api/v1/images/<sha256>` (served with the session cookie and access checks). Existing Markdown is converted once by a
migration; the API still accepts Markdown.

**Consequences.** + Sanitising by construction; equal content has equal bytes (no false versions, exact round trips —
Word and Markdown round trips are lossless for editor content). + One place to extend for new formats.
− A deliberately limited HTML subset (no colours, fonts or arbitrary styles); ReqIF drops the start number of
numbered lists (not in its XHTML subset).
