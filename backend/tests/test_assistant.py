"""The AI assistant: reading tools, proposals that only change data after the person confirms, the person's role,
error handling and the audit trail. The language model is replaced by a scripted fake, so the tests say what the
application does with an answer — not what a model happens to say."""

import json

import httpx
import pytest
from conftest import new_item
from sqlalchemy import select

from almlight.core.config import get_settings
from almlight.core.errors import ValidationFailed
from almlight.modules.assistant import llm


class FakeModel:
    """Answers a scripted list of replies and records what it was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen: list[list[dict]] = []
        self.tools: list[list[dict]] = []

    def __call__(self, messages, tools=None, **kw):
        self.seen.append(messages)
        self.tools.append(tools or [])
        if not self.replies:
            return llm.Reply(content="(no further answer)")
        return self.replies.pop(0)

    @property
    def tool_names(self) -> set[str]:
        return {t["function"]["name"] for t in (self.tools[-1] if self.tools else [])}


TOOL_SCHEMA = {"type": "function", "function": {"name": "search_items", "description": "Find items",
                                               "parameters": {"type": "object", "properties": {}}}}


def call(name, args, cid="c1"):
    return llm.Reply(tool_calls=[llm.ToolCall(id=cid, name=name, arguments=args)])


@pytest.fixture
def configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "azure_openai_endpoint", "https://example.invalid")
    monkeypatch.setattr(s, "azure_openai_api_key", "k")
    monkeypatch.setattr(s, "azure_openai_deployment", "gpt-test")
    monkeypatch.setattr(s, "assistant_api", "auto")
    llm._quirks.clear()  # what a deployment needs is learned per process
    return s


def model(monkeypatch, *replies) -> FakeModel:
    fake = FakeModel(*replies)
    monkeypatch.setattr(llm, "chat", fake)
    return fake


def thread_of(api, project) -> str:
    return api.post(f"/projects/{project}/assistant/threads", expect=201)["id"]


def test_assistant_is_off_until_it_is_configured(team, project):
    c = team["contributor"]
    info = c.get(f"/projects/{project}/assistant")
    assert info["enabled"] is False and info["model"] is None and info["threads"] == []
    tid = thread_of(c, project)
    err = c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "Hello?"}, expect=422)
    assert "not configured" in err["error"]["message"]


def test_it_answers_from_the_project_with_its_tools(team, project, configured, monkeypatch, db):
    c = team["contributor"]
    new_item(c, project, "system_requirement", "Measure gauge pressure 0-10 bar")
    new_item(c, project, "system_requirement", "Withstand vibration")
    fake = model(monkeypatch,
                 call("search_items", {"types": ["system_requirement"], "limit": 10}),
                 llm.Reply(content="The project has 2 system requirements.", usage={"total_tokens": 42}))
    tid = thread_of(c, project)
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "How many requirements?"})

    assert [m["role"] for m in out["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert out["messages"][-1]["content"] == "The project has 2 system requirements."
    assert out["pending"] == [] and out["title"] == "How many requirements?"
    found = json.loads(out["messages"][2]["content"])
    assert found["total"] == 2 and {i["title"] for i in found["items"]} == {"Measure gauge pressure 0-10 bar",
                                                                           "Withstand vibration"}
    assert out["messages"][2]["meta"] == {"call_id": "c1", "name": "search_items", "ok": True}
    # the model was given the project in its system prompt, the question, and then the tool answer
    assert fake.seen[0][0]["role"] == "system" and f"project {project}" in fake.seen[0][0]["content"]
    assert "role there is contributor" in fake.seen[0][0]["content"]
    assert [m["role"] for m in fake.seen[1]] == ["system", "user", "assistant", "tool"]
    assert fake.seen[1][2]["tool_calls"][0]["function"]["name"] == "search_items"
    assert fake.seen[1][3]["tool_call_id"] == "c1"
    # the question is in the audit trail, the conversation in the list
    from almlight.modules.audit.models import AuditEntry

    entry = db.execute(select(AuditEntry).where(AuditEntry.action == "assistant.asked")).scalar_one()
    assert entry.details["question"] == "How many requirements?"
    assert c.get(f"/projects/{project}/assistant")["threads"][0]["title"] == "How many requirements?"


def test_a_change_is_only_made_after_the_person_confirms(team, project, configured, monkeypatch, db):
    c = team["contributor"]
    fake = model(monkeypatch,
                 call("create_item", {"type": "system_requirement", "title": "Survive salt spray",
                                      "description": "The housing shall survive 480 h salt spray.",
                                      "fields": {"priority": "must"}}),
                 llm.Reply(content="I proposed the requirement."),
                 llm.Reply(content="Created as SYS-1."))
    tid = thread_of(c, project)
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "Add a salt spray requirement"})

    # the proposal carries an exact preview — and nothing exists yet
    assert len(out["pending"]) == 1
    proposal = out["pending"][0]
    assert proposal["summary"] == "Create System Requirement: “Survive salt spray”"
    assert proposal["preview"]["created"] == "SYS-1" and proposal["error"] is None
    assert c.get(f"/projects/{project}/items?q=salt")["total"] == 0
    assert fake.seen[-1][-1]["role"] == "user"  # the model has not seen a tool answer for the proposal yet

    # discarding leaves the project untouched and tells the model
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/confirm", {"approve": False})
    assert c.get(f"/projects/{project}/items?q=salt")["total"] == 0
    assert out["pending"] == [] and json.loads(out["messages"][2]["content"])["not_executed"]
    assert out["messages"][-1]["content"] == "I proposed the requirement."

    # asking again and confirming applies it, with a normal version and the audit trail
    fake.replies = [call("create_item", {"type": "system_requirement", "title": "Survive salt spray",
                                         "fields": {"priority": "must"}}, cid="c2"),
                    llm.Reply(content="Created as SYS-1.")]
    c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "Do add it"})
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/confirm", {"approve": True})
    assert out["pending"] == [] and out["messages"][-1]["content"] == "Created as SYS-1."
    created = c.get(f"/projects/{project}/items?q=salt")["items"]
    assert len(created) == 1 and created[0]["fields"]["priority"] == "must"
    key = created[0]["key"]
    versions = c.get(f"/projects/{project}/items/{key}/versions")
    assert versions[-1]["change_note"] == "Created by the assistant"
    from almlight.modules.audit.models import AuditEntry

    applied = db.execute(select(AuditEntry).where(AuditEntry.action == "assistant.applied")).scalar_one()
    assert applied.details["proposals"] == ["Create System Requirement: “Survive salt spray”"]
    assert db.execute(select(AuditEntry).where(AuditEntry.action == "item.created")).scalar_one().actor_name == "carla"


def test_it_edits_an_existing_item_and_shows_what_changes(team, project, configured, monkeypatch):
    c = team["contributor"]
    key = new_item(c, project, "system_requirement", "Measuring range", fields={"priority": "could"})["key"]
    model(monkeypatch,
          call("update_item", {"key": key, "title": "Measuring range 0-10 bar",
                               "fields": {"priority": "must"}, "reason": "Sharpened after the review"}),
          llm.Reply(content="Proposed."), llm.Reply(content="Done."))
    tid = thread_of(c, project)
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "Make the range a must"})
    preview = out["pending"][0]["preview"]
    assert preview["before"]["title"] == "Measuring range" and preview["after"]["title"] == "Measuring range 0-10 bar"
    assert preview["before"]["fields"]["priority"] == "could" and preview["after"]["fields"]["priority"] == "must"
    assert c.get(f"/projects/{project}/items/{key}")["title"] == "Measuring range"  # not yet

    c.post(f"/projects/{project}/assistant/threads/{tid}/confirm", {"approve": True})
    item = c.get(f"/projects/{project}/items/{key}")
    assert item["title"] == "Measuring range 0-10 bar" and item["version"] == "A.2"
    assert c.get(f"/projects/{project}/items/{key}/versions")[0]["change_note"] == "Sharpened after the review"


def test_readers_get_no_writing_tools_and_cannot_apply(team, project, configured, monkeypatch, make_user):
    v = team["viewer"]
    fake = model(monkeypatch, llm.Reply(content="You can only read here."))
    tid = thread_of(v, project)
    info = v.get(f"/projects/{project}/assistant")
    assert info["can_change"] is False and all(not t["writes"] for t in info["tools"])
    v.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "Create a requirement"})
    assert fake.tool_names == {"project_overview", "search_items", "get_item", "coverage", "impact", "history"}
    assert "only read" in fake.seen[0][0]["content"]

    # even if the model asks for a change, the tool refuses and the conversation goes on
    fake.replies = [call("create_item", {"type": "system_requirement", "title": "Nope"}),
                    llm.Reply(content="I cannot change anything.")]
    out = v.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "Please create it anyway"})
    assert out["pending"] == []
    assert "contributor" in json.loads(out["messages"][-2]["content"])["error"]
    assert v.get(f"/projects/{project}/items?q=Nope")["total"] == 0

    # conversations are private to the person who had them
    other, _ = make_user("contributor", project)
    other.get(f"/projects/{project}/assistant/threads/{tid}", expect=404)
    other.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "hi"}, expect=404)
    assert other.get(f"/projects/{project}/assistant")["threads"] == []


def test_a_failing_tool_does_not_break_the_conversation(team, project, configured, monkeypatch):
    c = team["contributor"]
    model(monkeypatch,
          call("get_item", {"key": "SYS-999"}),
          call("search_items", {"query_language": "state:::broken"}, cid="c2"),
          llm.Reply(content="I could not find it."))
    tid = thread_of(c, project)
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "What is SYS-999?"})
    assert "not found" in json.loads(out["messages"][2]["content"])["error"]
    assert out["messages"][2]["meta"]["ok"] is False
    assert json.loads(out["messages"][4]["content"])["error"]  # an unusable filter comes back as an error, not a crash
    assert out["messages"][-1]["content"] == "I could not find it."


def test_the_conversation_stops_instead_of_looping(team, project, configured, monkeypatch):
    c = team["contributor"]
    monkeypatch.setattr(get_settings(), "assistant_max_steps", 3)
    model(monkeypatch, *[call("project_overview", {}, cid=f"c{n}") for n in range(5)])
    tid = thread_of(c, project)
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "Loop please"})
    assert out["messages"][-1]["content"].startswith("I stopped after several steps")
    assert sum(1 for m in out["messages"] if m["role"] == "tool") == 3


def test_overview_and_coverage_give_the_model_the_project_model(team, project, configured, monkeypatch):
    c = team["contributor"]
    key = new_item(c, project, "system_requirement", "Measure pressure")["key"]
    model(monkeypatch, call("project_overview", {}), call("coverage", {"type": "system_requirement"}, cid="c2"),
          llm.Reply(content="One requirement, not verified."))
    tid = thread_of(c, project)
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "How is the coverage?"})
    overview = json.loads(out["messages"][2]["content"])
    types = {t["key"] for t in overview["item_types"]}
    assert {"system_requirement", "test_case"} <= types and overview["your_role"] == "contributor"
    req = next(t for t in overview["item_types"] if t["key"] == "system_requirement")
    assert "priority" in {f["key"] for f in req["fields"]} and "draft" in req["states"]
    assert overview["statistics"]["total_items"] == 1
    assert "priority" in overview["query_fields"] and "state" in overview["query_fields"]
    cov = json.loads(out["messages"][4]["content"])
    assert cov["total"] == 1 and cov["with_tests_pct"] == 0
    gap = cov["items_with_gaps"][0]
    assert gap == {"key": key, "title": "Measure pressure", "refined_by": 0, "satisfied_by": 0,
                   "test_cases": 0, "verification": "none"}


def test_it_finds_traceability_gaps_with_one_search(team, project, configured, monkeypatch):
    """"Which requirements have no test case" is a link filter — the query language has no field for it."""
    c = team["contributor"]
    covered = new_item(c, project, "system_requirement", "Measuring range")["key"]
    open_one = new_item(c, project, "system_requirement", "Vibration")["key"]
    test = new_item(c, project, "test_case", "Range test")["key"]
    c.post(f"/projects/{project}/links", {"type": "verifies", "source": test, "target": covered}, expect=201)
    fake = model(monkeypatch,
                 call("search_items", {"types": ["system_requirement"], "link_type": "verifies",
                                       "link_direction": "incoming", "has_link": False}),
                 llm.Reply(content=f"Only {open_one} has no test case."))
    tid = thread_of(c, project)
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/messages",
                 {"text": "Which requirements have no test case?"})
    found = json.loads(out["messages"][2]["content"])
    assert [i["key"] for i in found["items"]] == [open_one] and found["total"] == 1

    # the other direction and an unknown link type are answered usefully, not with a crash
    fake.replies = [call("search_items", {"types": ["system_requirement"], "link_type": "verifies",
                                          "link_direction": "incoming", "has_link": True}, cid="c2"),
                    call("search_items", {"link_type": "nonsense", "has_link": False}, cid="c3"),
                    llm.Reply(content="done")]
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "And which ones have one?"})
    answers = {m["meta"]["call_id"]: json.loads(m["content"]) for m in out["messages"] if m["role"] == "tool"}
    assert [i["key"] for i in answers["c2"]["items"]] == [covered]
    assert "Unknown link type" in answers["c3"]["error"]


def test_conversations_are_listed_and_can_be_deleted(team, project, configured, monkeypatch, db):
    c = team["contributor"]
    model(monkeypatch, llm.Reply(content="Hello."), llm.Reply(content="Hello again."))
    first, second = thread_of(c, project), thread_of(c, project)
    c.post(f"/projects/{project}/assistant/threads/{first}/messages", {"text": "First question"})
    c.post(f"/projects/{project}/assistant/threads/{second}/messages", {"text": "Second question"})
    assert [t["title"] for t in c.get(f"/projects/{project}/assistant")["threads"]] == ["Second question",
                                                                                        "First question"]
    c.delete(f"/projects/{project}/assistant/threads/{first}")
    assert [t["title"] for t in c.get(f"/projects/{project}/assistant")["threads"]] == ["Second question"]
    from almlight.modules.assistant.models import AssistantMessage

    assert db.execute(select(AssistantMessage)).scalars().all() != []  # only the deleted thread's messages are gone
    c.get(f"/projects/{project}/assistant/threads/{first}", expect=404)


def test_the_model_answer_is_checked_before_it_is_used(team, project, configured, monkeypatch):
    """Everything the model sends is foreign input: broken arguments and odd answers must not break the loop."""
    c = team["contributor"]
    assert llm._parse_arguments('{"key": "SYS-1"}') == {"key": "SYS-1"}
    assert llm._parse_arguments("not json")["__invalid__"] == "not json"
    assert llm._parse_arguments("[1, 2]")["__invalid__"] == [1, 2]
    assert llm._parse_arguments(None) == {}
    model(monkeypatch, call("get_item", {"__invalid__": "SYS-1"}), llm.Reply(content=""))
    tid = thread_of(c, project)
    out = c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "?"})
    assert "item key" in json.loads(out["messages"][2]["content"])["error"]
    assert out["messages"][-1]["content"] == "…"  # an empty answer is still shown as a message


def test_nothing_to_confirm_and_long_questions_are_refused(team, project, configured, monkeypatch):
    c = team["contributor"]
    model(monkeypatch, llm.Reply(content="ok"))
    tid = thread_of(c, project)
    err = c.post(f"/projects/{project}/assistant/threads/{tid}/confirm", {"approve": True}, expect=422)
    assert "nothing waiting" in err["error"]["message"]
    c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "   "}, expect=422)
    c.post(f"/projects/{project}/assistant/threads/{tid}/messages", {"text": "x" * 9000}, expect=422)


class FakeHttp:
    """Stands in for the Azure endpoint: answers a scripted list and records every request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json))
        status, body = self.answers.pop(0) if self.answers else (200, {})
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))


CHAT_ANSWER = {"choices": [{"message": {"content": "", "tool_calls": [
    {"id": "c1", "type": "function", "function": {"name": "search_items", "arguments": '{"limit": 5}'}}]},
    "finish_reason": "tool_calls"}], "usage": {"total_tokens": 7}}
# what Azure says when a reasoning model is asked for tools on chat completions (seen on a real deployment)
NEEDS_RESPONSES = {"error": {"param": "reasoning_effort", "type": "invalid_request_error", "message":
                   "Function tools with reasoning_effort are not supported for this model in /v1/chat/completions."
                   " To use function tools, use /v1/responses or set reasoning_effort to 'none'."}}
RESPONSES_ANSWER = {"status": "completed", "output": [
    {"type": "reasoning", "summary": []},
    {"type": "function_call", "call_id": "call_abc", "name": "search_items", "arguments": '{"limit": 5}'}],
    "usage": {"total_tokens": 82}}


def test_a_classic_deployment_is_asked_on_chat_completions(configured, monkeypatch):
    http = FakeHttp((200, CHAT_ANSWER))
    monkeypatch.setattr(llm.httpx, "post", http)
    reply = llm.chat([{"role": "user", "content": "hi"}], [TOOL_SCHEMA])
    url, body = http.calls[0]
    assert url.endswith("/openai/deployments/gpt-test/chat/completions?api-version=2024-10-21")
    assert body["messages"][0]["content"] == "hi" and body["temperature"] == 0.1
    assert body["tools"][0]["function"]["name"] == "search_items" and body["tool_choice"] == "auto"
    assert reply.tool_calls[0].name == "search_items" and reply.tool_calls[0].arguments == {"limit": 5}


def test_a_reasoning_deployment_switches_to_the_responses_api(configured, monkeypatch):
    """A model that refuses tools on chat completions is asked again on the responses API — and stays there."""
    http = FakeHttp((400, NEEDS_RESPONSES), (200, RESPONSES_ANSWER), (200, {"status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": "Es gibt **8 Anforderungen**."}]}]}))
    monkeypatch.setattr(llm.httpx, "post", http)
    reply = llm.chat([{"role": "system", "content": "You are the assistant."},
                      {"role": "user", "content": "Wie viele?"}], [TOOL_SCHEMA])
    assert [u.split("/openai/")[1].split("?")[0] for u, _ in http.calls] == [
        "deployments/gpt-test/chat/completions", "responses"]
    url, body = http.calls[1]
    assert "api-version=2025-04-01-preview" in url
    assert body["model"] == "gpt-test" and body["store"] is False and "temperature" not in body
    assert body["input"] == [{"role": "system", "content": "You are the assistant."},
                             {"role": "user", "content": "Wie viele?"}]
    assert body["tools"][0] == {"type": "function", "name": "search_items", "description": "Find items",
                                "parameters": {"type": "object", "properties": {}}}
    assert reply.tool_calls[0].id == "call_abc" and reply.tool_calls[0].arguments == {"limit": 5}
    assert reply.usage == {"total_tokens": 82}

    # the next round goes straight to the responses API and carries the tool result in its shape
    reply = llm.chat([{"role": "user", "content": "Wie viele?"},
                      {"role": "assistant", "content": "", "tool_calls": [
                          {"id": "call_abc", "type": "function",
                           "function": {"name": "search_items", "arguments": '{"limit": 5}'}}]},
                      {"role": "tool", "tool_call_id": "call_abc", "content": '{"total": 8}'}], [TOOL_SCHEMA])
    assert len(http.calls) == 3 and http.calls[2][0].endswith("responses?api-version=2025-04-01-preview")
    assert http.calls[2][1]["input"][1:] == [
        {"type": "function_call", "call_id": "call_abc", "name": "search_items", "arguments": '{"limit": 5}'},
        {"type": "function_call_output", "call_id": "call_abc", "output": '{"total": 8}'}]
    assert reply.content == "Es gibt **8 Anforderungen**." and reply.tool_calls == []


def test_a_model_that_refuses_the_temperature_is_asked_again_without_it(configured, monkeypatch):
    http = FakeHttp((400, {"error": {"param": "temperature", "message": "Unsupported value: 'temperature'"}}),
                    (200, CHAT_ANSWER))
    monkeypatch.setattr(llm.httpx, "post", http)
    llm.chat([{"role": "user", "content": "hi"}], [TOOL_SCHEMA])
    assert "temperature" in http.calls[0][1] and "temperature" not in http.calls[1][1]


def test_the_surface_can_be_pinned_and_a_real_error_is_not_retried(configured, monkeypatch):
    monkeypatch.setattr(configured, "assistant_api", "responses")
    monkeypatch.setattr(configured, "assistant_reasoning_effort", "low")
    http = FakeHttp((400, NEEDS_RESPONSES))
    monkeypatch.setattr(llm.httpx, "post", http)
    with pytest.raises(ValidationFailed, match="answered with an error"):
        llm.chat([{"role": "user", "content": "hi"}], [TOOL_SCHEMA])
    assert len(http.calls) == 1 and http.calls[0][0].endswith("responses?api-version=2025-04-01-preview")
    assert http.calls[0][1]["reasoning"] == {"effort": "low"}


def test_what_the_model_sends_back_is_read_defensively(configured, monkeypatch):
    monkeypatch.setattr(configured, "assistant_api", "responses")
    monkeypatch.setattr(llm.httpx, "post", FakeHttp((200, {"output": [
        "nonsense", {"type": "message", "content": [{"type": "refusal", "text": "no"}]},
        {"type": "function_call", "name": "", "arguments": "{}"},
        {"type": "function_call", "call_id": "x", "name": "get_item", "arguments": "not json"}]})))
    reply = llm.chat([{"role": "user", "content": "hi"}])
    assert reply.content == "" and [c.name for c in reply.tool_calls] == ["get_item"]
    assert reply.tool_calls[0].arguments == {"__invalid__": "not json"}
