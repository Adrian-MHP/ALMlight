"""Revision label schemes: letters (A, B, ..., Z, AA, AB, ...) or numbers (1, 2, 3, ...)."""

from __future__ import annotations


def first_revision(scheme: str) -> str:
    return "1" if scheme == "numbers" else "A"


def next_revision(label: str, scheme: str) -> str:
    if scheme == "numbers":
        return str(int(label) + 1)
    # Base-26 increment without zero: Z -> AA, AZ -> BA, ZZ -> AAA.
    chars = list(label)
    i = len(chars) - 1
    while i >= 0:
        if chars[i] != "Z":
            chars[i] = chr(ord(chars[i]) + 1)
            return "".join(chars)
        chars[i] = "A"
        i -= 1
    return "A" + "".join(chars)
