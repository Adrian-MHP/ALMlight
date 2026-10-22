"""Applicability expressions for the 150% model.

An item or link may carry an expression over feature codes, e.g.
``OUT_HART and (SIL2 or SIL3) and not ATEX``. It is evaluated against the set of
features selected in a variant. Grammar (case-insensitive keywords)::

    expr    := or
    or      := and (("or" | "||") and)*
    and     := not (("and" | "&&") not)*
    not     := ("not" | "!") not | atom
    atom    := IDENT | "true" | "false" | "(" expr ")"

A small recursive-descent parser — never ``eval``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from almlight.core.errors import ValidationFailed

_TOKEN = re.compile(r"\s*(?:(\(|\)|&&|\|\||!)|([A-Za-z][A-Za-z0-9_]*))")
MAX_LENGTH = 2000


@dataclass(frozen=True)
class Node:
    op: str  # ident | const | not | and | or
    value: str | bool | None = None
    children: tuple[Node, ...] = ()


def _tokenize(expr: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    expr = expr.rstrip()
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            raise ValidationFailed(f"Invalid applicability expression near '{expr[pos:pos + 12]}'")
        tokens.append(m.group(1) or m.group(2))
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> str | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise ValidationFailed("Applicability expression ends unexpectedly")
        self.i += 1
        return tok

    def parse(self) -> Node:
        node = self.parse_or()
        if self.peek() is not None:
            raise ValidationFailed(f"Unexpected token '{self.peek()}' in applicability expression")
        return node

    def parse_or(self) -> Node:
        parts = [self.parse_and()]
        while (tok := self.peek()) is not None and tok.lower() in ("or", "||"):
            self.take()
            parts.append(self.parse_and())
        return parts[0] if len(parts) == 1 else Node("or", children=tuple(parts))

    def parse_and(self) -> Node:
        parts = [self.parse_not()]
        while (tok := self.peek()) is not None and tok.lower() in ("and", "&&"):
            self.take()
            parts.append(self.parse_not())
        return parts[0] if len(parts) == 1 else Node("and", children=tuple(parts))

    def parse_not(self) -> Node:
        tok = self.peek()
        if tok is not None and tok.lower() in ("not", "!"):
            self.take()
            return Node("not", children=(self.parse_not(),))
        return self.parse_atom()

    def parse_atom(self) -> Node:
        tok = self.take()
        low = tok.lower()
        if tok == "(":
            node = self.parse_or()
            if self.take() != ")":
                raise ValidationFailed("Missing ')' in applicability expression")
            return node
        if low in ("true", "false"):
            return Node("const", value=(low == "true"))
        if low in ("and", "or", "not") or tok in (")", "&&", "||", "!"):
            raise ValidationFailed(f"Unexpected '{tok}' in applicability expression")
        return Node("ident", value=tok)


def parse(expr: str) -> Node:
    if len(expr) > MAX_LENGTH:
        raise ValidationFailed("Applicability expression is too long")
    tokens = _tokenize(expr)
    if not tokens:
        return Node("const", value=True)
    return _Parser(tokens).parse()


def normalize(expr: str | None) -> str | None:
    """Validate the syntax; returns None for empty expressions (= always applicable)."""
    if expr is None or not expr.strip():
        return None
    parse(expr)
    return expr.strip()


def evaluate(node: Node, selected: set[str]) -> bool:
    if node.op == "const":
        return bool(node.value)
    if node.op == "ident":
        return node.value in selected
    if node.op == "not":
        return not evaluate(node.children[0], selected)
    if node.op == "and":
        return all(evaluate(c, selected) for c in node.children)
    return any(evaluate(c, selected) for c in node.children)


def identifiers(node: Node) -> set[str]:
    if node.op == "ident":
        return {str(node.value)}
    out: set[str] = set()
    for c in node.children:
        out |= identifiers(c)
    return out


def applies(expr: str | None, selected: set[str]) -> bool:
    return True if not expr else evaluate(parse(expr), selected)
