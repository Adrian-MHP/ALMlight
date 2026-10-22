"""Rich text: one content model, many formats.

Item texts are stored as *canonical HTML*: a small, safe subset (paragraphs, headings, lists, quotes, code,
tables, images, links, inline marks and item references) serialised in exactly one way. Every input — HTML from
the editor, Markdown or plain text from the API, ReqIF XHTML, Word content, the collaborative editor's Yjs
document — is parsed into the same block model and written back by one serialiser. Consequences:

* content is sanitised by construction (only known elements, attributes and URL schemes are ever emitted);
* the same content always has the same bytes, so unchanged text never creates a new version or a false diff;
* Word, PDF, ReqIF and plain-text renderers all read the same model.

Images are never embedded: they live in the content-addressed file store and are referenced as
``/api/v1/images/<sha256>``. Whoever parses input supplies an image resolver that turns a source into such a
reference (or drops it), e.g. by storing a pasted ``data:`` image.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html import escape
from typing import Any

IMAGE_PREFIX = "/api/v1/images/"
IMAGE_SRC = re.compile(r"^/api/v1/images/([0-9a-f]{64})$")
MAX_HTML = 2_000_000

# Canonical nesting order of inline marks (outermost first).
MARK_ORDER = ("link", "strong", "em", "u", "s", "sup", "sub", "code", "mark")
MARK_TAGS = {"strong": "strong", "em": "em", "u": "u", "s": "s", "sup": "sup", "sub": "sub", "code": "code",
             "mark": "mark"}
_HTML_MARKS = {"strong": "strong", "b": "strong", "em": "em", "i": "em", "cite": "em", "dfn": "em", "var": "em",
               "u": "u", "ins": "u", "s": "s", "strike": "s", "del": "s", "code": "code", "kbd": "code",
               "samp": "code", "tt": "code", "sub": "sub", "sup": "sup", "mark": "mark"}
_DROP = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math", "canvas", "form",
         "input", "button", "select", "textarea", "video", "audio", "source", "track", "link", "meta", "head",
         "title", "base", "frame", "frameset", "applet", "param", "map", "area", "picture"}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_PARA_LIKE = {"p", "div", "section", "article", "header", "footer", "aside", "nav", "main", "center", "address",
              "dd", "dt", "figcaption", "caption", "summary", "details", "legend", "fieldset", "dl", "figure"}
_ALIGN = {"left", "center", "right", "justify"}
_WS = re.compile(r"[ \t\r\n\f\v]+")


# --- model -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Run:
    text: str
    marks: tuple[tuple[str, str], ...] = ()  # ordered (name, value); value is the href for links


@dataclass(frozen=True)
class Atom:
    kind: str  # br | itemref
    key: str = ""
    marks: tuple[tuple[str, str], ...] = ()


Inline = Run | Atom


@dataclass
class Block:
    kind: str  # p | h | ul | ol | li | quote | pre | hr | img | table | tr | cell
    inlines: list[Inline] = field(default_factory=list)
    children: list[Block] = field(default_factory=list)
    text: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)


ImageResolver = Callable[[str, dict[str, Any]], str | None]


def keep_stored_images(src: str, attrs: dict[str, Any]) -> str | None:
    """Default resolver: only images already in the store are kept."""
    return src if IMAGE_SRC.match(src or "") else None


# --- helpers ---------------------------------------------------------------------------------------------


def _order(marks: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    seen: dict[str, str] = {}
    for name, value in marks:
        if name in MARK_ORDER and name not in seen:
            seen[name] = value
    return tuple((n, seen[n]) for n in MARK_ORDER if n in seen)


def safe_href(href: str | None) -> str | None:
    if not href:
        return None
    h = "".join(ch for ch in href.strip() if ch >= " ")
    low = h.lower()
    if low.startswith(("http://", "https://", "mailto:")):
        return h[:2000]
    if (h.startswith("/") and not h.startswith("//")) or h.startswith("#"):
        return h[:2000]
    return None


def _int_attr(value: Any, lo: int = 1, hi: int = 10_000) -> int | None:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _normalize_inlines(items: list[Inline]) -> list[Inline]:
    """Collapse whitespace, merge runs with equal marks, trim paragraph edges and spaces around breaks."""
    out: list[Inline] = []
    for it in items:
        if isinstance(it, Run):
            text = _WS.sub(" ", it.text)
            if not text:
                continue
            if out and isinstance(out[-1], Run):
                prev = out[-1]
                if prev.text.endswith(" ") and text.startswith(" "):
                    text = text[1:]
                    if not text:
                        continue
                if prev.marks == it.marks:
                    out[-1] = Run(prev.text + text, it.marks)
                    continue
            out.append(Run(text, it.marks))
        else:
            out.append(it)

    def trim(seq: list[Inline], left: bool) -> None:
        idx = 0 if left else -1
        while seq and isinstance(seq[idx], Run):
            r = seq[idx]
            t = r.text.lstrip(" ") if left else r.text.rstrip(" ")
            if t:
                seq[idx] = Run(t, r.marks)
                break
            seq.pop(idx)

    trim(out, True)
    trim(out, False)
    # spaces next to hard breaks are not significant
    res: list[Inline] = []
    for i, it in enumerate(out):
        if isinstance(it, Run):
            t = it.text
            if i > 0 and isinstance(out[i - 1], Atom) and out[i - 1].kind == "br":
                t = t.lstrip(" ")
            if i + 1 < len(out) and isinstance(out[i + 1], Atom) and out[i + 1].kind == "br":
                t = t.rstrip(" ")
            if t:
                res.append(Run(t, it.marks))
        else:
            res.append(it)
    while res and isinstance(res[-1], Atom) and res[-1].kind == "br":
        res.pop()
    # merge again after trimming
    merged: list[Inline] = []
    for it in res:
        if merged and isinstance(it, Run) and isinstance(merged[-1], Run) and merged[-1].marks == it.marks:
            merged[-1] = Run(merged[-1].text + it.text, it.marks)
        else:
            merged.append(it)
    return merged


def _is_empty_para(b: Block) -> bool:
    return b.kind == "p" and not b.inlines


def _trim_blocks(blocks: list[Block]) -> list[Block]:
    while blocks and _is_empty_para(blocks[0]):
        blocks.pop(0)
    while blocks and _is_empty_para(blocks[-1]):
        blocks.pop()
    return blocks


def _ensure_blocks(blocks: list[Block]) -> list[Block]:
    return blocks or [Block("p")]


# --- HTML -> model ---------------------------------------------------------------------------------


class _Sink:
    """Collects inline content and blocks; inline runs between blocks become paragraphs (or headings)."""

    def __init__(self, para_kind: str = "p", attrs: dict[str, Any] | None = None):
        self.blocks: list[Block] = []
        self.inlines: list[Inline] = []
        self.para_kind = para_kind
        self.attrs = attrs or {}

    def flush(self, force: bool = False) -> None:
        inl = _normalize_inlines(self.inlines)
        if inl or force:
            self.blocks.append(Block(self.para_kind, inlines=inl, attrs=dict(self.attrs)))
        self.inlines = []

    def block(self, b: Block) -> None:
        self.flush()
        self.blocks.append(b)


class _HtmlParser:
    def __init__(self, resolver: ImageResolver):
        self.resolver = resolver

    def parse(self, html: str) -> list[Block]:
        from lxml import etree
        from lxml import html as lhtml

        html = (html or "")[:MAX_HTML]
        if not html.strip():
            return []
        try:
            root = lhtml.fragment_fromstring(html, create_parent="div")
        except (etree.ParserError, ValueError):
            return []
        sink = _Sink()
        self._children(root, sink, ())
        sink.flush()
        return _trim_blocks(sink.blocks)

    # -- walking --

    @staticmethod
    def _tag(el: Any) -> str | None:
        tag = el.tag
        if not isinstance(tag, str):
            return None  # comment / processing instruction
        return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()

    def _children(self, el: Any, sink: _Sink, marks: tuple) -> None:
        if el.text:
            sink.inlines.append(Run(el.text, _order(marks)))
        for child in el:
            self._walk(child, sink, marks)
            if child.tail:
                sink.inlines.append(Run(child.tail, _order(marks)))

    def _span_marks(self, el: Any, marks: tuple) -> tuple:
        style = (el.get("style") or "").lower().replace(" ", "")
        extra = []
        if re.search(r"font-weight:(bold|[6-9]00)", style):
            extra.append(("strong", ""))
        if "font-style:italic" in style:
            extra.append(("em", ""))
        if "underline" in style:
            extra.append(("u", ""))
        if "line-through" in style:
            extra.append(("s", ""))
        if "vertical-align:super" in style:
            extra.append(("sup", ""))
        if "vertical-align:sub" in style:
            extra.append(("sub", ""))
        if re.search(r"background(-color)?:(?!transparent|none|#fff\b|#ffffff|white)", style):
            extra.append(("mark", ""))
        if "monospace" in style or "courier" in style or "consolas" in style:
            extra.append(("code", ""))
        return marks + tuple(extra)

    def _align(self, el: Any) -> str | None:
        style = (el.get("style") or "").lower()
        m = re.search(r"text-align\s*:\s*(left|center|right|justify)", style)
        align = m.group(1) if m else (el.get("align") or "").lower() or None
        return align if align in _ALIGN and align != "left" else None

    def _walk(self, el: Any, sink: _Sink, marks: tuple) -> None:
        tag = self._tag(el)
        if tag is None or tag in _DROP:
            return
        if tag in _HTML_MARKS:
            self._children(el, sink, marks + ((_HTML_MARKS[tag], ""),))
        elif tag == "a":
            href = safe_href(el.get("href"))
            ref = re.fullmatch(r"#item:([A-Z][A-Z0-9]{0,7}-\d+)", href or "")
            if ref:
                sink.inlines.append(Atom("itemref", key=ref.group(1), marks=_order(marks)))
            else:
                self._children(el, sink, marks + ((("link", href),) if href else ()))
        elif tag == "br":
            sink.inlines.append(Atom("br", marks=_order(marks)))
        elif tag == "span" and el.get("data-type") in ("item-ref", "itemRef"):
            key = (el.get("data-key") or el.get("data-id") or el.text_content() or "").strip().upper()
            if re.fullmatch(r"[A-Z][A-Z0-9]{0,7}-\d+", key):
                sink.inlines.append(Atom("itemref", key=key, marks=_order(marks)))
        elif tag in ("span", "font", "small", "big", "abbr", "acronym", "label", "q", "time", "bdi", "bdo",
                     "wbr", "nobr", "data", "output", "ruby", "rb", "rt", "rp"):
            self._children(el, sink, self._span_marks(el, marks) if tag in ("span", "font") else marks)
        elif tag == "img":
            self._image(el, sink)
        elif tag in _HEADINGS:
            self._paragraph(el, sink, "h", {"level": _HEADINGS[tag], **self._align_attr(el)}, marks)
        elif tag == "p":
            self._paragraph(el, sink, "p", self._align_attr(el), marks)
        elif tag in _PARA_LIKE:
            if any(self._tag(c) in _BLOCKISH for c in el):
                sink.flush()
                self._children(el, sink, marks)
                sink.flush()
            else:
                self._paragraph(el, sink, "p", self._align_attr(el), marks)
        elif tag in ("ul", "ol", "menu", "dir"):
            sink.block(self._list(el, "ol" if tag == "ol" else "ul"))
        elif tag == "li":
            sink.block(Block("ul", children=[self._container(el, "li")]))
        elif tag == "blockquote":
            sink.block(self._container(el, "quote"))
        elif tag in ("pre", "listing", "xmp", "plaintext"):
            sink.block(Block("pre", text=self._pre_text(el)))
        elif tag == "hr":
            sink.block(Block("hr"))
        elif tag == "table":
            t = self._table(el)
            if t is not None:
                sink.block(t)
        elif tag in ("thead", "tbody", "tfoot", "tr", "td", "th", "colgroup", "col"):
            # stray table parts outside a table: keep their content
            sink.flush()
            self._children(el, sink, marks)
            sink.flush()
        else:
            self._children(el, sink, marks)

    def _align_attr(self, el: Any) -> dict[str, Any]:
        a = self._align(el)
        return {"align": a} if a else {}

    def _paragraph(self, el: Any, sink: _Sink, kind: str, attrs: dict[str, Any], marks: tuple) -> None:
        sink.flush()
        inner = _Sink(kind, attrs)
        self._children(el, inner, marks)
        inner.flush()
        for b in inner.blocks:
            sink.blocks.append(b)
        if not inner.blocks and kind == "p":
            sink.blocks.append(Block("p"))

    def _container(self, el: Any, kind: str) -> Block:
        inner = _Sink()
        self._children(el, inner, ())
        inner.flush()
        return Block(kind, children=_ensure_blocks(_trim_blocks(inner.blocks)))

    def _list(self, el: Any, kind: str) -> Block:
        items: list[Block] = []
        loose = _Sink()
        if el.text and el.text.strip():
            loose.inlines.append(Run(el.text))
        for child in el:
            ctag = self._tag(child)
            if ctag == "li":
                if loose.inlines or loose.blocks:
                    loose.flush()
                    items.append(Block("li", children=_ensure_blocks(loose.blocks)))
                    loose = _Sink()
                items.append(self._container(child, "li"))
            elif ctag in ("ul", "ol"):
                nested = self._list(child, "ol" if ctag == "ol" else "ul")
                if items:
                    items[-1].children.append(nested)
                else:
                    items.append(Block("li", children=[Block("p"), nested]))
            elif ctag is not None and ctag not in _DROP:
                self._walk(child, loose, ())
            if child.tail and child.tail.strip():
                loose.inlines.append(Run(child.tail))
        if loose.inlines or loose.blocks:
            loose.flush()
            items.append(Block("li", children=_ensure_blocks(loose.blocks)))
        attrs: dict[str, Any] = {}
        if kind == "ol":
            start = _int_attr(el.get("start"), 0, 100_000)
            if start is not None and start != 1:
                attrs["start"] = start
        return Block(kind, children=items or [Block("li", children=[Block("p")])], attrs=attrs)

    def _pre_text(self, el: Any) -> str:
        parts: list[str] = []

        def rec(e: Any) -> None:
            if e.text:
                parts.append(e.text)
            for c in e:
                if self._tag(c) == "br":
                    parts.append("\n")
                elif self._tag(c) not in _DROP:
                    rec(c)
                if c.tail:
                    parts.append(c.tail)

        rec(el)
        return "".join(parts).replace("\r\n", "\n").replace("\r", "\n").strip("\n")

    def _image(self, el: Any, sink: _Sink) -> None:
        attrs = {"alt": (el.get("alt") or "").strip()[:500], "title": (el.get("title") or "").strip()[:500],
                 "width": _int_attr(el.get("width")), "height": _int_attr(el.get("height"))}
        src = self.resolver(el.get("src") or "", attrs)
        if not src:
            if attrs["alt"]:
                sink.inlines.append(Run(f"[{attrs['alt']}]"))
            return
        sink.block(Block("img", attrs={"src": src, **{k: v for k, v in attrs.items() if v}}))

    def _table(self, el: Any) -> Block | None:
        rows: list[Block] = []

        def collect(e: Any) -> None:
            for c in e:
                ctag = self._tag(c)
                if ctag == "tr":
                    cells = []
                    for td in c:
                        ttag = self._tag(td)
                        if ttag not in ("td", "th"):
                            continue
                        cell = self._container(td, "cell")
                        cell.attrs = {"header": ttag == "th"}
                        cs, rs = _int_attr(td.get("colspan"), 1, 100), _int_attr(td.get("rowspan"), 1, 1000)
                        if cs and cs > 1:
                            cell.attrs["colspan"] = cs
                        if rs and rs > 1:
                            cell.attrs["rowspan"] = rs
                        cells.append(cell)
                    if cells:
                        rows.append(Block("tr", children=cells))
                elif ctag in ("thead", "tbody", "tfoot"):
                    collect(c)

        collect(el)
        return Block("table", children=rows) if rows else None


_BLOCKISH = {"p", "div", "ul", "ol", "table", "blockquote", "pre", "hr", "img", "h1", "h2", "h3", "h4", "h5", "h6",
             "section", "article", "figure", "dl", "dt", "dd", "li", "header", "footer", "center", "address",
             "figcaption", "caption", "details", "summary", "aside", "nav", "main", "fieldset"}


def parse_html(html: str, resolver: ImageResolver = keep_stored_images) -> list[Block]:
    return _HtmlParser(resolver).parse(html)


# --- model -> canonical HTML -----------------------------------------------------------------------------


def _attr(name: str, value: Any) -> str:
    return f' {name}="{escape(str(value), quote=True)}"'


def _open_mark(name: str, value: str) -> str:
    if name == "link":
        return f'<a href="{escape(value, quote=True)}">'
    return f"<{MARK_TAGS[name]}>"


def _close_mark(name: str) -> str:
    return "</a>" if name == "link" else f"</{MARK_TAGS[name]}>"


def inline_html(inlines: list[Inline]) -> str:
    out: list[str] = []
    stack: list[tuple[str, str]] = []
    for it in inlines:
        marks = list(it.marks)
        common = 0
        while common < len(stack) and common < len(marks) and stack[common] == marks[common]:
            common += 1
        while len(stack) > common:
            out.append(_close_mark(stack.pop()[0]))
        for m in marks[common:]:
            out.append(_open_mark(*m))
            stack.append(m)
        if isinstance(it, Run):
            out.append(escape(it.text, quote=False))
        elif it.kind == "br":
            out.append("<br>")
        elif it.kind == "itemref":
            k = escape(it.key, quote=True)
            out.append(f'<span data-type="item-ref" data-key="{k}">{k}</span>')
    while stack:
        out.append(_close_mark(stack.pop()[0]))
    return "".join(out)


def _block_html(b: Block) -> str:
    k = b.kind
    if k in ("p", "h"):
        tag = "p" if k == "p" else f"h{b.attrs.get('level', 2)}"
        align = b.attrs.get("align")
        style = _attr("style", f"text-align: {align}") if align else ""
        return f"<{tag}{style}>{inline_html(b.inlines)}</{tag}>"
    if k in ("ul", "ol"):
        start = _attr("start", b.attrs["start"]) if k == "ol" and b.attrs.get("start") else ""
        return f"<{k}{start}>" + "".join(_block_html(li) for li in b.children) + f"</{k}>"
    if k == "li":
        return "<li>" + "".join(_block_html(c) for c in _ensure_blocks(b.children)) + "</li>"
    if k == "quote":
        return "<blockquote>" + "".join(_block_html(c) for c in _ensure_blocks(b.children)) + "</blockquote>"
    if k == "pre":
        return f"<pre><code>{escape(b.text, quote=False)}</code></pre>"
    if k == "hr":
        return "<hr>"
    if k == "img":
        a = b.attrs
        parts = [_attr("src", a["src"])]
        for name in ("alt", "title", "width", "height"):
            if a.get(name):
                parts.append(_attr(name, a[name]))
        return "<img" + "".join(parts) + ">"
    if k == "table":
        rows = []
        for tr in b.children:
            cells = []
            for c in tr.children:
                tag = "th" if c.attrs.get("header") else "td"
                span = "".join(_attr(n, c.attrs[n]) for n in ("colspan", "rowspan") if c.attrs.get(n))
                cells.append(f"<{tag}{span}>" + "".join(_block_html(x) for x in _ensure_blocks(c.children))
                             + f"</{tag}>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return "<table><tbody>" + "".join(rows) + "</tbody></table>"
    return ""


def to_html(blocks: list[Block]) -> str:
    return "".join(_block_html(b) for b in _trim_blocks(list(blocks)))


def canonical(html: str, resolver: ImageResolver = keep_stored_images) -> str:
    """Sanitise and normalise HTML into the canonical form (idempotent)."""
    return to_html(parse_html(html, resolver))


# --- other inputs -------------------------------------------------------------------------------------------

_HTML_START = re.compile(
    r"^\s*(<!--.*?-->\s*)*<(p|div|h[1-6]|ul|ol|li|table|thead|tbody|tr|td|th|blockquote|pre|hr|br|img|strong|b|"
    r"em|i|u|s|a|span|code|sub|sup|mark|figure|section|article|font|center|dl|xhtml:[a-z]+)[\s>/]",
    re.IGNORECASE | re.DOTALL)


def looks_like_html(text: str) -> bool:
    return bool(_HTML_START.match(text or ""))


def markdown_to_html(md: str) -> str:
    from markdown_it import MarkdownIt

    md_parser = MarkdownIt("commonmark", {"html": False, "breaks": False}).enable(["table", "strikethrough"])
    rendered = md_parser.render(md or "").replace("&lt;br&gt;", "<br>")
    return canonical(rendered)


def plain_to_html(text: str) -> str:
    paras = re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").replace("\r", "\n").strip())
    blocks = []
    for p in paras:
        if not p.strip():
            continue
        inl: list[Inline] = []
        for i, line in enumerate(p.split("\n")):
            if i:
                inl.append(Atom("br"))
            inl.append(Run(line))
        blocks.append(Block("p", inlines=_normalize_inlines(inl)))
    return to_html(blocks)


def normalize_input(value: str | None, resolver: ImageResolver = keep_stored_images) -> str:
    """Text from the API: HTML is sanitised; anything else is read as Markdown (a superset of plain text)."""
    value = value or ""
    if not value.strip():
        return ""
    if looks_like_html(value):
        return canonical(value, resolver)
    return markdown_to_html(value)


# --- model -> text -----------------------------------------------------------------------------------------


def inline_text(inlines: list[Inline]) -> str:
    out = []
    for it in inlines:
        if isinstance(it, Run):
            out.append(it.text)
        elif it.kind == "br":
            out.append("\n")
        else:
            out.append(it.key)
    return "".join(out)


def _block_text(b: Block, prefix: str = "") -> list[str]:
    k = b.kind
    if k in ("p", "h"):
        return [inline_text(b.inlines)]
    if k in ("ul", "ol"):
        lines = []
        for n, li in enumerate(b.children, start=b.attrs.get("start", 1)):
            marker = f"{n}. " if k == "ol" else "- "
            sub = [ln for c in li.children for ln in _block_text(c)]
            if sub:
                lines.append(marker + sub[0])
                lines.extend("   " + s for s in sub[1:])
        return ["\n".join(lines)]
    if k == "quote":
        return ["\n".join("> " + ln for c in b.children for ln in _block_text(c))]
    if k == "pre":
        return [b.text]
    if k == "hr":
        return ["---"]
    if k == "img":
        alt = b.attrs.get("alt")
        return [f"[image: {alt}]" if alt else "[image]"]
    if k == "table":
        rows = []
        for tr in b.children:
            rows.append(" | ".join(" ".join(t for c in cell.children for t in _block_text(c)).replace("\n", " ")
                                   for cell in tr.children))
        return ["\n".join(rows)]
    return []


def blocks_text(blocks: list[Block]) -> str:
    return "\n\n".join(t for b in blocks for t in _block_text(b) if t.strip()).strip()


def to_text(html: str) -> str:
    """Readable plain text (CSV/Excel export, previews, plain-text consumers)."""
    return blocks_text(parse_html(html, lambda s, a: s or "x"))


def text_key(text: str) -> str:
    """Whitespace-insensitive comparison key for plain-text round trips."""
    return _WS.sub(" ", (text or "").replace(" ", " ")).strip()


# --- model -> Markdown (spreadsheet round trips) -------------------------------------------------------------

_MD_ESCAPE = re.compile(r"([\\`*_\[\]<>|~])")


def _md_inline(inlines: list[Inline], in_table: bool = False) -> str:
    out: list[str] = []
    for it in inlines:
        if isinstance(it, Atom):
            if it.kind == "br":
                out.append("<br>" if in_table else "\\\n")
            else:
                out.append(f"[{it.key}](#item:{it.key})")
            continue
        marks = dict(it.marks)
        if "code" in marks:
            tick = "``" if "`" in it.text else "`"
            text = f"{tick}{it.text}{tick}"
        else:
            text = _MD_ESCAPE.sub(r"\\\1", it.text)
            core = text.strip()
            if core and ("strong" in marks or "em" in marks or "s" in marks):
                lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()):]
                if "s" in marks:
                    core = f"~~{core}~~"
                if "em" in marks:
                    core = f"*{core}*"
                if "strong" in marks:
                    core = f"**{core}**"
                text = f"{lead}{core}{trail}"
        if "link" in marks:
            text = f"[{text}]({marks['link']})"
        out.append(text)
    md = "".join(out)
    if in_table:
        return md
    md = re.sub(r"^(\d+)([.)])", r"\1\\\2", md)
    return re.sub(r"^([#+\-=])", r"\\\1", md)


def _md_block(b: Block, indent: str = "") -> list[str]:
    k = b.kind
    if k == "p":
        return [indent + _md_inline(b.inlines).replace("\n", "\n" + indent)]
    if k == "h":
        return [indent + "#" * int(b.attrs.get("level", 2)) + " " + _md_inline(b.inlines)]
    if k in ("ul", "ol"):
        lines: list[str] = []
        for n, li in enumerate(b.children, start=int(b.attrs.get("start", 1))):
            marker = f"{n}. " if k == "ol" else "- "
            pad = " " * len(marker)
            parts = ["\n".join(_md_block(c, pad)) for c in li.children]
            first = parts[0].lstrip() if parts else ""
            lines.append(indent + marker + first)
            for extra in parts[1:]:
                lines.append("")
                lines.extend(indent + ln for ln in extra.split("\n"))
        return ["\n".join(lines)]
    if k == "quote":
        inner = "\n\n".join(x for c in b.children for x in _md_block(c))
        return ["\n".join(indent + "> " + ln if ln else indent + ">" for ln in inner.split("\n"))]
    if k == "pre":
        fence = "````" if "```" in b.text else "```"
        return [indent + fence + "\n" + "\n".join(indent + ln for ln in b.text.split("\n")) + "\n" + indent + fence]
    if k == "hr":
        return [indent + "---"]
    if k == "img":
        alt = _MD_ESCAPE.sub(r"\\\1", b.attrs.get("alt", ""))
        return [indent + f"![{alt}]({b.attrs['src']})"]
    if k == "table":
        rows = b.children
        simple = rows and all(not c.attrs.get("colspan") and not c.attrs.get("rowspan")
                              for r in rows for c in r.children)
        if simple:
            width = max(len(r.children) for r in rows)

            def cell(c: Block) -> str:
                return "<br>".join(_md_inline(x.inlines, True) for x in c.children if x.kind in ("p", "h"))

            md_rows = [[cell(c) for c in r.children] + [""] * (width - len(r.children)) for r in rows]
            lines = ["| " + " | ".join(md_rows[0]) + " |", "|" + " --- |" * width]
            lines += ["| " + " | ".join(r) + " |" for r in md_rows[1:]]
            return ["\n".join(indent + ln for ln in lines)]
        return [indent + ln for ln in blocks_text([b]).split("\n")]
    return []


def to_markdown(html: str) -> str:
    """Markdown rendering for spreadsheets: formatting, lists, tables, links and images survive a round trip."""
    return "\n\n".join(x for b in parse_html(html, lambda s, a: s) for x in _md_block(b)).strip()


# --- diff, hashing, misc --------------------------------------------------------------------------------------


def html_diff(old: str, new: str) -> str:
    """Word-level difference of two canonical HTML texts, marked with <ins>/<del> (formatting kept)."""
    from lxml.html.diff import htmldiff

    if (old or "") == (new or ""):
        return new or ""
    try:
        return htmldiff(old or "", new or "")
    except Exception:  # noqa: BLE001 — diff of malformed input: fall back to plain text
        return escape(to_text(new))


def content_hash(title: str, description: str) -> str:
    """Identifies the text state a collaborative editing session starts from."""
    return hashlib.sha256(f"{title}\x00{description}".encode()).hexdigest()[:16]


def image_shas(html: str) -> set[str]:
    return set(re.findall(r'/api/v1/images/([0-9a-f]{64})', html or ""))


def walk_blocks(blocks: list[Block]) -> Iterable[Block]:
    for b in blocks:
        yield b
        yield from walk_blocks(b.children)
