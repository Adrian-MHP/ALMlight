# 19 The AI assistant (0.9)

An assistant that works **inside one project**: it answers from the project's data, puts evaluations together, and
proposes changes that the person applies or discards. It is switched off until a language model is configured, and
it can never see or do more than the person chatting with it.

## 19.1 What it can do

Open it with the sparkles button in the header while a project is open. It has these tools, and it uses them
instead of guessing:

| Tool | What it does |
|---|---|
| `project_overview` | The information model — item types with their fields, states and link types — plus the project's numbers. It calls this before it uses a type or field name. |
| `search_items` | Finds items: by words, by a filter in the project's query language (`type:system_requirement state:approved`, `priority:must`, `updated:-7d`, `owner:me` — `project_overview` names the fields), and by traceability (`link_type=verifies, link_direction=incoming, has_link=false` are the requirements nothing verifies). |
| `get_item` | One item in full: description, fields, owner, state, version, links, attachments. |
| `coverage` | Traceability coverage of an item type and the items with gaps. |
| `impact` | What a change of an item would affect. |
| `history` | What happened in the project, or to one item, and who did it. |
| `create_item`, `update_item`, `create_link`, `add_comment` | Changes — **proposed only**, see below. |

So the questions it is good at are the ones whose answer is in the project: *Which requirements have no test case?
Summarise the open change requests. What would change if SYS-1 changes? Which items did Rita change last week?
Draft a test case for SYS-4.*

## 19.2 Changes need the person

The model never changes anything by itself. When it calls a changing tool, the server

1. runs the change in a **savepoint and rolls it back**, so the preview is exactly what would happen (including
   validation errors — a wrong field value shows up as an error, not as a surprise later),
2. shows the person what would change (for an edit: the fields before and after), and
3. applies it only on **Apply**, or drops it on **Discard**.

An applied change goes through the normal services: it gets a normal item version with the change note "Created by
the assistant" (or the reason the assistant gave), it marks links suspect as any other change would, and it lands
in the audit trail as the person's own change — next to an `assistant.applied` entry that records what was
proposed. Nothing the assistant does bypasses a workflow, a frozen state or the release rules.

## 19.3 Permissions and privacy

- The assistant acts **as the person chatting**: every tool runs through the normal services with their role. A
  reader is not even offered the changing tools, and they are refused if the model asks for them anyway.
- Conversations are **private to the person** who had them (not visible to other members or to managers) and are
  stored in the project's database. Delete one in the panel.
- Only what the assistant reads for the question travels to the language model: the system prompt (project key and
  name, the person's name and role), the conversation, and the answers of the tools it called. The key stays on
  the server; it is never sent to the browser.
- The question itself is recorded in the audit trail (`assistant.asked`) so an installation can tell who asked
  what — that is also the reason not to type secrets into the chat.
- **The data leaves the installation.** With Azure OpenAI it goes to the resource in your tenant and region; check
  that the deployment you configure has the data-protection terms your project needs before you point the
  assistant at real customer data.

## 19.4 Configuration

Set the three variables (see [operations](08-operations.md) §8.3) and restart:

```bash
ALMLIGHT_AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
ALMLIGHT_AZURE_OPENAI_API_KEY=<key of the Azure OpenAI resource>
ALMLIGHT_AZURE_OPENAI_DEPLOYMENT=<name of the deployment, e.g. gpt-4o>
```

The deployment name is the one from Azure AI Foundry, not the model name, and the model has to support **tool
calling** — without it the assistant can only chat and never reads the project.

Azure has two surfaces for that, and Ariadne picks the right one by itself: classic **chat completions** (GPT-4o
and the like) and the **responses** API, which reasoning models require for tools. On the first question the
assistant tries chat completions; if the deployment answers "to use function tools, use /v1/responses" it repeats
the request there and stays on it (visible once in the log). Requests to the responses API carry `store: false`,
so the conversation is not kept at the provider.

| Variable | Default | Purpose |
|---|---|---|
| `ALMLIGHT_AZURE_OPENAI_API_VERSION` | `2024-10-21` | version for chat completions |
| `ALMLIGHT_AZURE_OPENAI_RESPONSES_API_VERSION` | `2025-04-01-preview` | version for the responses API |
| `ALMLIGHT_ASSISTANT_API` | `auto` | `chat` or `responses` pins the surface instead of letting it be detected |
| `ALMLIGHT_ASSISTANT_REASONING_EFFORT` | – | `low`, `medium`, `high` for reasoning models (more thinking, slower and dearer) |

On Azure Container Apps the key belongs in a secret, like the other secrets in
[18](18-azure-container-apps.md).

Without configuration the panel says so and names the variables; nothing else in the application changes.

## 19.5 Limits

- One question can take several model calls (`ALMLIGHT_ASSISTANT_MAX_STEPS`, default 6) and holds a database
  connection while it runs — fine for a team, not for dozens of people asking at once.
- The answer appears when it is finished; there is no token-by-token streaming yet.
- The assistant sees the last `ALMLIGHT_ASSISTANT_MAX_HISTORY` messages (default 40) of the conversation, and a
  tool answer is cut off at 30,000 characters — it then asks for a narrower question.
- It proposes one step at a time: a change of twenty items is twenty proposals, which is deliberate. Bulk edit
  (see [15](15-work-management.md)) is the tool for that.
- It reads items, links, coverage, impact and history. Documents, baselines, plans, the BOM, test runs and the Git
  commits are not tools yet — ask about the items behind them instead.
- The e2e tests use a stand-in for the model (`e2e/llm_stub.py`), so the browser tests do not need a cloud service;
  the backend tests script the model directly.
