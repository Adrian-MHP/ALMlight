"""A stand-in for the language model, so the browser tests can exercise the whole assistant.

It speaks the Azure OpenAI chat-completions API that ``modules/assistant/llm.py`` calls, and answers by simple
rules instead of by thinking: a question about a number makes it search, a request to add something makes it
propose a new item, and a tool answer makes it reply with what came back. Only used by compose.test.yaml.
"""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8000


def reply(content=None, tool=None, arguments=None):
    message = {"role": "assistant", "content": content}
    if tool:
        message["tool_calls"] = [{"id": "stub-1", "type": "function",
                                  "function": {"name": tool, "arguments": json.dumps(arguments or {})}}]
    return {"choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool else "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}


def answer(messages):
    last = messages[-1]
    if last.get("role") == "tool":
        try:
            data = json.loads(last.get("content") or "{}")
        except ValueError:
            data = {}
        if "total" in data:
            return reply(f"Das Projekt hat **{data['total']}** Systemanforderungen.")
        if "created" in data:
            return reply(f"Angelegt als {data['created']}.")
        if "not_executed" in data:
            return reply("Nicht ausgeführt — nichts wurde geändert.")
        if "error" in data:
            return reply(f"Das ging nicht: {data['error']}")
        return reply("Fertig.")
    text = (last.get("content") or "").lower()
    if "lege" in text or "anlegen" in text or "add " in text:
        title = re.sub(r"^.*?(?:anforderung|requirement)\s*", "", text).strip(" .:") or "Neue Anforderung"
        return reply(None, "create_item", {"type": "system_requirement", "title": title.capitalize()[:80],
                                           "description": "Vom Assistenten vorgeschlagen.",
                                           "fields": {"priority": "should"}})
    if "wie viele" in text or "how many" in text:
        return reply(None, "search_items", {"types": ["system_requirement"], "limit": 50})
    return reply("Ich bin der Test-Assistent. Frag mich nach Anzahlen oder bitte mich, etwas anzulegen.")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 — name required by BaseHTTPRequestHandler
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            messages = json.loads(body)["messages"]
            out = answer(messages)
        except Exception as exc:  # noqa: BLE001 — the stub must answer something the app can read
            out = reply(f"stub error: {exc}")
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"language-model stub on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
