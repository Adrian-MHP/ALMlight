"""Server-side translations: error messages, activity and notification texts, e-mail digests and exports.

English is the source language. ``locales/<lang>.json`` holds ``messages`` (English message templates with ``{}``
for variable parts -> translation with ``{1}``, ``{2}`` … in any order) and ``texts`` (fixed texts with ``{name}``
placeholders). The language of a request is the user's saved language, else the browser's ``Accept-Language``.
Stored texts (audit summaries, notifications) stay English in the database and are translated when shown.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Request

SUPPORTED = ("en", "de")
_DIR = Path(__file__).resolve().parent.parent / "locales"


@lru_cache
def catalogue(locale: str) -> dict[str, dict[str, str]]:
    path = _DIR / f"{locale}.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {"messages": {}, "texts": {}}


@lru_cache
def _patterns(locale: str) -> list[tuple[re.Pattern[str], str]]:
    out = []
    for en, target in catalogue(locale).get("messages", {}).items():
        rx = "^" + "(.+?)".join(re.escape(p) for p in en.split("{}")) + "$"
        out.append((re.compile(rx, re.S), target, len(en.replace("{}", ""))))
    out.sort(key=lambda x: -x[2])  # the most specific template wins
    return [(r, t) for r, t, _ in out]


def tr(message: str | None, locale: str | None) -> str | None:
    """Translate a server message or stored summary; unknown texts stay as they are."""
    if not message or not locale or locale == "en" or locale not in SUPPORTED:
        return message
    for rx, target in _patterns(locale):
        found = rx.match(message)
        if found:
            return _fill(target, found.groups())
    return message


def _fill(target: str, parts: tuple[str | Any, ...]) -> str:
    return re.sub(r"\{(\d+)\}", lambda g: parts[int(g.group(1)) - 1] or "", target)


def t(locale: str | None, en: str, **values: Any) -> str:
    """A fixed server text (e-mail, export labels) in the given language."""
    text = en if not locale or locale == "en" else catalogue(locale).get("texts", {}).get(en, en)
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def parse_accept_language(header: str | None) -> str:
    for part in (header or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in SUPPORTED:
            return code
    return "en"


def request_locale(request: Request) -> str:
    """The user's saved language (set while authenticating the request), else the browser's language."""
    return getattr(request.state, "locale", None) or parse_accept_language(request.headers.get("accept-language"))


def label(project: Any, text: str | None, locale: str | None) -> str | None:
    """A label of the project's information model in the given language (the model's own translations)."""
    if not text or not locale or locale == "en":
        return text
    return project.model.translations.get(locale, {}).get(text) or catalogue(locale).get("texts", {}).get(text, text)
