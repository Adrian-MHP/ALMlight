"""Reading the editor's shared document (Yjs XML as written by TipTap / y-prosemirror) into rich text.

Node names are the editor's ProseMirror node types (``paragraph``, ``heading``, ``bulletList`` …); marks are
formatting attributes of text runs (``bold``, ``italic``, ``link`` …). The result goes through the same
canonical serialiser as every other input.
"""

from __future__ import annotations

import re
from typing import Any

from pycrdt import XmlElement, XmlFragment, XmlText

from almlight.core.richtext import (
    IMAGE_SRC,
    Atom,
    Block,
    Inline,
    Run,
    _ensure_blocks,
    _normalize_inlines,
    _order,
    _trim_blocks,
    canonical,
    safe_href,
    to_html,
)

BODY, TITLE = "body", "title"
_MARKS = {"bold": "strong", "italic": "em", "underline": "u", "strike": "s", "code": "code", "subscript": "sub",
          "superscript": "sup", "highlight": "mark"}
_ALIGN = {"center", "right", "justify"}


def _int(v: Any, default: int | None = None) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _marks(attrs: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    out = []
    for name, value in (attrs or {}).items():
        base = name.split("--", 1)[0]
        if base in _MARKS:
            out.append((_MARKS[base], ""))
        elif base == "link" and isinstance(value, dict):
            href = safe_href(value.get("href"))
            if href:
                out.append(("link", href))
    return _order(out)


def _inlines(el: XmlElement) -> tuple[list[Inline], list[Block]]:
    inl: list[Inline] = []
    images: list[Block] = []
    for child in el.children:
        if isinstance(child, XmlText):
            for text, attrs in child.diff():
                if isinstance(text, str):
                    inl.append(Run(text, _marks(attrs)))
        elif isinstance(child, XmlElement):
            if child.tag == "hardBreak":
                inl.append(Atom("br"))
            elif child.tag == "itemRef":
                a = dict(child.attributes)
                key = str(a.get("key") or a.get("id") or "").upper()
                if re.fullmatch(r"[A-Z][A-Z0-9]{0,7}-\d+", key):
                    inl.append(Atom("itemref", key=key))
            elif child.tag == "image":
                images.extend(_node(child))
    return _normalize_inlines(inl), images


def _children(el: XmlElement | XmlFragment) -> list[Block]:
    return [b for c in el.children for b in _node(c)]


def _node(el: Any) -> list[Block]:
    if isinstance(el, XmlText):
        runs = [Run(t, _marks(a)) for t, a in el.diff() if isinstance(t, str)]
        inl = _normalize_inlines(runs)
        return [Block("p", inlines=inl)] if inl else []
    if not isinstance(el, XmlElement):
        return []
    tag = el.tag
    attrs = dict(el.attributes)
    align = attrs.get("textAlign") if attrs.get("textAlign") in _ALIGN else None
    if tag in ("paragraph", "heading"):
        inl, images = _inlines(el)
        extra: dict[str, Any] = {"align": align} if align else {}
        if tag == "heading":
            extra["level"] = max(1, min(_int(attrs.get("level"), 2) or 2, 6))
        blocks = [Block("p" if tag == "paragraph" else "h", inlines=inl, attrs=extra)] if inl or not images else []
        return blocks + images
    if tag in ("bulletList", "orderedList"):
        items = [Block("li", children=_ensure_blocks(_trim_blocks(_children(li)))) for li in el.children
                 if isinstance(li, XmlElement)]
        b = Block("ol" if tag == "orderedList" else "ul", children=items or [Block("li", children=[Block("p")])])
        start = _int(attrs.get("start"), 1)
        if tag == "orderedList" and start not in (None, 1):
            b.attrs["start"] = start
        return [b]
    if tag == "listItem":
        return [Block("ul", children=[Block("li", children=_ensure_blocks(_trim_blocks(_children(el))))])]
    if tag == "blockquote":
        return [Block("quote", children=_ensure_blocks(_trim_blocks(_children(el))))]
    if tag == "codeBlock":
        text = "".join(t for c in el.children if isinstance(c, XmlText) for t, _ in c.diff() if isinstance(t, str))
        return [Block("pre", text=text)]
    if tag == "horizontalRule":
        return [Block("hr")]
    if tag == "image":
        src = str(attrs.get("src") or "")
        if not IMAGE_SRC.match(src):
            return []
        a: dict[str, Any] = {"src": src}
        for name in ("alt", "title"):
            if attrs.get(name):
                a[name] = str(attrs[name])[:500]
        for name in ("width", "height"):
            n = _int(attrs.get(name))
            if n and 0 < n <= 10_000:
                a[name] = n
        return [Block("img", attrs=a)]
    if tag == "table":
        rows = []
        for tr in el.children:
            if not isinstance(tr, XmlElement):
                continue
            cells = []
            for c in tr.children:
                if not isinstance(c, XmlElement):
                    continue
                ca = dict(c.attributes)
                cell = Block("cell", children=_ensure_blocks(_trim_blocks(_children(c))),
                             attrs={"header": c.tag == "tableHeader"})
                for n in ("colspan", "rowspan"):
                    v = _int(ca.get(n), 1)
                    if v and v > 1:
                        cell.attrs[n] = v
                cells.append(cell)
            if cells:
                rows.append(Block("tr", children=cells))
        return [Block("table", children=rows)] if rows else []
    return _children(el)


def body_html(frag: XmlFragment) -> str:
    return canonical(to_html(_children(frag)), lambda src, attrs: src if IMAGE_SRC.match(src or "") else None)


def title_text(frag: XmlFragment) -> str:
    parts: list[str] = []

    def walk(el: Any) -> None:
        for c in el.children:
            if isinstance(c, XmlText):
                parts.extend(t for t, _ in c.diff() if isinstance(t, str))
            elif isinstance(c, XmlElement):
                walk(c)
                parts.append(" ")

    walk(frag)
    return re.sub(r"\s+", " ", "".join(parts)).strip()[:500]
