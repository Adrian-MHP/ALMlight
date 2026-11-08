"""A stand-in for the language model, so the browser tests can exercise the whole assistant.

It speaks the Azure OpenAI chat-completions API that ``modules/assistant/llm.py`` calls — and, on the Ollama
paths, stands in for a local model server as well, so the model picker can be tested too. It answers by simple
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


LOCAL_MODELS = {"models": [{"name": "qwen3:8b"}]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 — name required by BaseHTTPRequestHandler
        self._send(LOCAL_MODELS if self.path.startswith("/api/tags") else {})

    def _send_stream(self, out):
        """The same answer as server-sent events: text in two pieces, tool calls in one."""
        message = out["choices"][0]["message"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def event(delta, finish=None):
            chunk = {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()

        if message.get("tool_calls"):
            event({"tool_calls": message["tool_calls"]}, "tool_calls")
        else:
            text = message.get("content") or ""
            half = len(text) // 2
            event({"content": text[:half]})
            event({"content": text[half:]}, "stop")
        self.wfile.write(b"data: [DONE]\n\n")

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            sent = json.loads(body)
            out = answer(sent["messages"])
            if sent.get("model", "").startswith("qwen"):  # the local model says who answered
                out["choices"][0]["message"]["content"] = (
                    (out["choices"][0]["message"]["content"] or "") + " (lokal beantwortet)").strip() or None
        except Exception as exc:  # noqa: BLE001 — the stub must answer something the app can read
            sent, out = {}, reply(f"stub error: {exc}")
        if sent.get("stream"):
            self._send_stream(out)
        else:
            self._send(out)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"language-model stub on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
