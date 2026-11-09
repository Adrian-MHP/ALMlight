"""A diagram as SVG, drawn on the server.

The same picture outside the editor: for a preview, for a download, and for anything that can show an image.
It is plain SVG with no script and no outside reference, so it is safe to embed and to serve.
"""

from __future__ import annotations

from html import escape
from typing import Any

# one colour per category of the information model, in the product's palette
FILL = {"requirement": "#eef2fb", "architecture": "#e8f5f6", "verification": "#eaf7ef", "change": "#fdf1e7",
        "risk": "#fdecec", "variability": "#f6edfa", "planning": "#e9f4fa", "document": "#f1f3f5",
        "other": "#f1f3f5"}
STROKE = {"requirement": "#4c6ef5", "architecture": "#0f8a94", "verification": "#2f9e68", "change": "#e8823a",
          "risk": "#d9534f", "variability": "#9c5fb5", "planning": "#3a92c4", "document": "#868e96",
          "other": "#868e96"}
TEXT = "#1f2d3d"
MUTED = "#6b7a8c"
PAD = 24
CHAR = 6.4  # width of a character at 11px in the font used below


def _wrap(text: str, width: float, lines: int) -> list[str]:
    """Break a title into at most ``lines`` lines that fit into ``width`` pixels."""
    per_line = max(8, int(width / CHAR))
    out: list[str] = []
    for word in (text or "").split():
        if out and len(out[-1]) + 1 + len(word) <= per_line:
            out[-1] += " " + word
        elif len(out) < lines:
            out.append(word[:per_line])
        else:
            break
    if len(out) == lines and len(" ".join(out)) < len(text or ""):
        out[-1] = out[-1][: max(1, per_line - 1)] + "…"
    return out or [""]


def _cut(text: str, width: float, char: float = 5.6) -> str:
    """One line that fits into ``width``: the type label must not run into the key in the other corner."""
    limit = max(3, int(width / char))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _edge_points(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, float, float, float]:
    """A straight line between two node centres, cut off at the edge of each box."""
    ax, ay = a["x"] + a["w"] / 2, a["y"] + a["h"] / 2
    bx, by = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ax, ay, bx, by

    def cut(cx: float, cy: float, node: dict[str, Any], sx: float, sy: float) -> tuple[float, float]:
        hw, hh = node["w"] / 2 + 2, node["h"] / 2 + 2
        scale = min(hw / abs(sx) if sx else 1e9, hh / abs(sy) if sy else 1e9)
        return cx + sx * scale, cy + sy * scale

    start = cut(ax, ay, a, dx, dy)
    end = cut(bx, by, b, -dx, -dy)
    return start[0], start[1], end[0], end[1]


def parallel(edges: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """How two relationships between the same pair stay apart: (bow, label offset).

    The bow pushes the curve sideways, the offset stacks the labels — a bow alone separates the lines but not
    their names, which are wider than the gap between them.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for e in edges:
        groups.setdefault(tuple(sorted((e["from"], e["to"]))), []).append(e["id"])
    out: dict[str, tuple[float, float]] = {}
    for members in groups.values():
        for i, edge_id in enumerate(members):
            off = i - (len(members) - 1) / 2
            out[edge_id] = (off * 26, off * 14)
    return out


def control(x1: float, y1: float, x2: float, y2: float, bow: float) -> tuple[float, float]:
    """The control point of the curve: the middle, pushed sideways by ``bow``."""
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    if not bow:
        return mx, my
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    return mx - dy / length * bow, my + dx / length * bow


def render(view: dict[str, Any], *, title: bool = True) -> str:
    nodes = {n["id"]: n for n in view["nodes"]}
    xs = [n["x"] for n in view["nodes"]] or [0]
    ys = [n["y"] for n in view["nodes"]] or [0]
    right = max((n["x"] + n["w"] for n in view["nodes"]), default=320)
    bottom = max((n["y"] + n["h"] for n in view["nodes"]), default=120)
    ox, oy = min(xs) - PAD, min(ys) - PAD - (26 if title else 0)
    width, height = right - ox + PAD, bottom - oy + PAD
    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{ox:.0f} {oy:.0f} {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}" font-family="Inter, Segoe UI, Arial, sans-serif">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{MUTED}"/></marker></defs>',
        f'<rect x="{ox:.0f}" y="{oy:.0f}" width="{width:.0f}" height="{height:.0f}" fill="#ffffff"/>',
    ]
    if title:
        out.append(f'<text x="{min(xs):.0f}" y="{oy + 18:.0f}" font-size="13" font-weight="600" fill="{TEXT}">'
                   f'{escape(view.get("title") or "")}</text>')
    bows = parallel(view["edges"])
    for edge in view["edges"]:
        a, b = nodes.get(edge["from"]), nodes.get(edge["to"])
        if a is None or b is None:
            continue
        x1, y1, x2, y2 = _edge_points(a, b)
        bow, label_dy = bows.get(edge["id"], (0.0, 0.0))
        cx, cy = control(x1, y1, x2, y2, bow)
        colour = "#d9534f" if edge.get("suspect") else MUTED
        out.append(f'<path d="M {x1:.1f} {y1:.1f} Q {cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}" fill="none" '
                   f'stroke="{colour}" stroke-width="1.3" marker-end="url(#arrow)"/>')
        if edge.get("label"):
            mx, my = (x1 + 2 * cx + x2) / 4, (y1 + 2 * cy + y2) / 4 + label_dy
            label = escape(edge["label"])
            out.append(f'<rect x="{mx - len(label) * CHAR / 2 - 3:.1f}" y="{my - 8:.1f}" '
                       f'width="{len(label) * CHAR + 6:.1f}" height="14" rx="3" fill="#ffffff" opacity="0.9"/>'
                       f'<text x="{mx:.1f}" y="{my + 3:.1f}" font-size="10" fill="{MUTED}" '
                       f'text-anchor="middle">{label}</text>')
    for n in view["nodes"]:
        x, y, w, h = n["x"], n["y"], n["w"], n["h"]
        if n.get("kind") == "note":
            out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="4" fill="#fffbe6" '
                       f'stroke="#e0c97f"/>')
            for i, line in enumerate(_wrap(n.get("text", ""), w - 16, 4)):
                out.append(f'<text x="{x + 8:.0f}" y="{y + 20 + i * 14:.0f}" font-size="11" fill="{TEXT}">'
                           f'{escape(line)}</text>')
            continue
        category = n.get("category", "other")
        missing = n.get("missing")
        fill = "#fdecec" if missing else FILL.get(category, FILL["other"])
        stroke = "#d9534f" if missing else STROKE.get(category, STROKE["other"])
        out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="5" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="1.2"/>')
        key_text = n.get("item") or ""
        type_label = _cut(n.get("type_label") or "", w - 40 - len(key_text) * 5.6)  # 40: margins and a gap
        out.append(f'<text x="{x + 10:.0f}" y="{y + 17:.0f}" font-size="10" fill="{stroke}" '
                   f'font-weight="600">{escape(type_label)}</text>')
        out.append(f'<text x="{x + w - 10:.0f}" y="{y + 17:.0f}" font-size="10" fill="{MUTED}" '
                   f'text-anchor="end">{escape(key_text)}</text>')
        title_lines = _wrap(n.get("title") or ("(deleted)" if missing else ""), w - 20, 2)
        for i, line in enumerate(title_lines):
            out.append(f'<text x="{x + 10:.0f}" y="{y + 36 + i * 15:.0f}" font-size="11.5" fill="{TEXT}">'
                       f'{escape(line)}</text>')
        if n.get("state"):
            out.append(f'<text x="{x + 10:.0f}" y="{y + h - 9:.0f}" font-size="9.5" fill="{MUTED}">'
                       f'{escape(n["state"])}</text>')
    out.append("</svg>")
    return "".join(out)
