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
| `documents` | The documents of the project, or one document with its headings and items in reading order — for summarising or reviewing a specification. |
| `plans` | Releases and iterations with dates, goal, progress and status; with a key also the work planned in it. |
| `bom` | The bill of materials under an item (levels, quantities, find numbers), or where an item is used. |
| `risks` | The risk register (FMEA): the numbers by level, how many are unmitigated, and the rows. |
| `revisions` | Code of the connected Git repositories: the commits, branches and pull requests of an item, or the latest commits. |
| `create_item`, `update_item`, `create_link`, `add_comment` | Changes — **proposed only**, see below. |

So the questions it is good at are the ones whose answer is in the project: *Which requirements have no test case?
Summarise the open change requests. What would change if SYS-1 changes? Which items did Rita change last week?
Draft a test case for SYS-4. Summarise the system specification. Is release 1.0 on track? Which products contain
the measuring cell? Which risks are still unmitigated? What was committed for SYS-1?*

The answer appears **while it is written**, and the tool activity shows as it happens, so a slow model (a local
one in particular) does not look stuck. If a model or a surface cannot stream, the answer simply arrives in one
piece.

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

## 19.4 Choosing the model

An installation can offer **several models**, and the panel lets the person pick one per conversation (the choice
is remembered for the next one). Two kinds:

- **Azure OpenAI** — the deployment from the configuration, one per installation.
- **A local server (Ollama)** — everything that server has, or the allow-list in `ALMLIGHT_OLLAMA_MODELS`. The
  list is read from the server every half minute; if it is off, the panel simply offers the cloud model and says
  nothing is wrong. Local models answer over Ollama's OpenAI-compatible endpoint, so the same tools work — the
  model has to support **tool calling** (qwen3 and the like do).

Why a local model: the project's data never leaves the machine, and simple lookups cost nothing. Why not always:
a small model reasons less well. In a measured comparison on the demo project, the cloud model answered "which
requirements have no test case" correctly in 12 s, while `qwen3:8b` took 42 s on a two-part counting question and
drew the wrong conclusion — it had searched only the approved requirements and reported that count as the total.
Tool answers are therefore cut shorter for local models (8,000 instead of 30,000 characters, because of the
smaller context), and every search answer now carries the filter it applied, so a number cannot be read as
"everything". Use a local model for lookups and drafts, the cloud model for anything you are going to rely on —
and check what the assistant says, whichever model wrote it.

A conversation keeps the model it started with (the picker locks once the first answer is in) and the answer
names the model that wrote it. `ALMLIGHT_ASSISTANT_DEFAULT_MODEL` sets what a new conversation starts with.

## 19.5 Configuration

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

### A local model server

```bash
ALMLIGHT_OLLAMA_URL=http://host.docker.internal:11434   # from the container, this is the host
# ALMLIGHT_OLLAMA_MODELS=qwen3:8b-40k                   # optional allow-list
# ALMLIGHT_ASSISTANT_DEFAULT_MODEL=ollama:qwen3:8b-40k  # what a new conversation starts with
```

Azure and a local server can be configured at the same time; either alone switches the assistant on. Mind the
**context**: Ollama gives a model the context its tag was built with, and the information model of a project is a
few thousand tokens — a tag with a large window (for example `qwen3:8b-40k`) answers noticeably better than the
4k default.

## 19.6 Limits

- One question can take several model calls (`ALMLIGHT_ASSISTANT_MAX_STEPS`, default 6) and holds a database
  connection while it runs — fine for a team, not for dozens of people asking at once.
- The assistant sees the last `ALMLIGHT_ASSISTANT_MAX_HISTORY` messages (default 40) of the conversation, and a
  tool answer is cut off at 30,000 characters — it then asks for a narrower question.
- It proposes one step at a time: a change of twenty items is twenty proposals, which is deliberate. Bulk edit
  (see [15](15-work-management.md)) is the tool for that.
- It reads items, links, coverage, impact, history, documents, plans, the BOM, risks and the Git commits.
  Baselines, variants, test runs and time records are not tools yet — ask about the items behind them instead.
- Streaming needs a connection that is not buffered. Behind a reverse proxy, switch buffering off for
  `/api/v1/projects/*/assistant/*` (the answer carries `X-Accel-Buffering: no`, which nginx honours).
- The e2e tests use a stand-in for the model (`e2e/llm_stub.py`), which also answers on the Ollama paths, so the
  browser tests cover the model picker without a cloud service; the backend tests script the model directly.
- A local model is slower than it looks: it runs on the machine that also runs the browser and the containers.
