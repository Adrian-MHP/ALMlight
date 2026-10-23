# ADR-0025 File check-out as a lock beside the version; Word templates with placeholders

**Context.** Files such as CAD models or Office documents are edited outside the browser; two people replacing the same
file lose work, and releasing an item while its file is being edited breaks the release. Separately, customers must
deliver documents in their corporate design, which the generated standard layout cannot match.

**Decision.** *Files:* a check-out is a separate row (item, attachment, user, note) — not part of the versioned
attachment data, so locks never leak into history. Replacing or removing a file checked out by someone else is
refused; check-in stores the new content as the next file revision (same attachment id, new item iteration) and ends
the check-out; holders or managers cancel check-outs (audited). Transitions into frozen states and change-order
releases list checked-out files as blockers. File history is derived from the item versions. Inline display is
limited to raster images (sandboxed) and PDF. *Word templates:* customers upload a `.docx`/`.dotx` per project; the
export opens it, copies missing heading/list/table styles and their numbering from the standard layout, fills
`{{…}}` placeholders in body, headers, footers and text boxes (also across runs), turns `{{toc}}` into a TOC field
and moves the generated content to `{{content}}`. Uploads are size- and zip-bomb-checked; macro files are refused.

**Consequences.** + PDM-like safety for files without a separate vault. + Corporate-design Word output without a
template designer; the round trip keeps working. − Check-out is advisory for downloads (anyone with read access can
still download). − PDF export does not use the Word template.
