"""The y-websocket wire protocol (lib0 encoding) — what the standard ``y-websocket`` browser provider speaks.

A message is ``varuint(type)`` followed by its payload: ``0`` sync (step 1 / step 2 / update, handled by
pycrdt), ``1`` awareness (presence: who is here, cursor, user name), ``2`` auth, ``3`` query awareness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

MSG_SYNC, MSG_AWARENESS, MSG_AUTH, MSG_QUERY_AWARENESS = 0, 1, 2, 3
SYNC_STEP1, SYNC_STEP2, SYNC_UPDATE = 0, 1, 2


def write_var_uint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


class Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def var_uint(self) -> int:
        n = shift = 0
        while True:
            if self.pos >= len(self.data):
                raise ValueError("truncated message")
            b = self.data[self.pos]
            self.pos += 1
            n |= (b & 0x7F) << shift
            if b < 0x80:
                return n
            shift += 7
            if shift > 63:
                raise ValueError("varint too long")

    def var_bytes(self) -> bytes:
        n = self.var_uint()
        if self.pos + n > len(self.data):
            raise ValueError("truncated message")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def var_string(self) -> str:
        return self.var_bytes().decode("utf-8")


def var_bytes(data: bytes) -> bytes:
    return write_var_uint(len(data)) + data


def var_string(s: str) -> bytes:
    return var_bytes(s.encode("utf-8"))


@dataclass
class AwarenessEntry:
    client_id: int
    clock: int
    state: str  # JSON text; "null" removes the client


def parse_awareness(update: bytes) -> list[AwarenessEntry]:
    r = Reader(update)
    return [AwarenessEntry(r.var_uint(), r.var_uint(), r.var_string()) for _ in range(r.var_uint())]


def encode_awareness(entries: list[AwarenessEntry]) -> bytes:
    body = write_var_uint(len(entries))
    for e in entries:
        body += write_var_uint(e.client_id) + write_var_uint(e.clock) + var_string(e.state)
    return body


def awareness_message(entries: list[AwarenessEntry]) -> bytes:
    return write_var_uint(MSG_AWARENESS) + var_bytes(encode_awareness(entries))


def stamp_user(state: str, user: dict) -> str:
    """Presence carries the *authenticated* user, whatever the client claims."""
    if state == "null":
        return state
    try:
        data = json.loads(state)
    except ValueError:
        return "null"
    if not isinstance(data, dict):
        return "null"
    data["user"] = {**(data.get("user") if isinstance(data.get("user"), dict) else {}), **user}
    return json.dumps(data, separators=(",", ":"))
