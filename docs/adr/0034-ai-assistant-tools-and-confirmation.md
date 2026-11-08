# ADR-0034 The AI assistant reads through the normal services and may only *propose* changes

**Context.** An assistant that can answer questions about a project has to reach its data, and the obvious ways are
all bad: a copy of the project in a vector store goes stale and loses permissions; letting a model write SQL opens
the database to anything it invents; and a free-text answer about requirements is worthless if it is not grounded in
what the project actually contains. At the same time the request was explicitly for an assistant that can also
*change* things — and unchecked writes into a requirements database by a language model are a safety problem, not a
feature.

**Decision.** The assistant is a tool-calling loop over the **existing services**, not a new data path. Each tool
(`search_items`, `get_item`, `project_overview`, `coverage`, `impact`, `history`, and the changing ones) runs inside
the request of the person who is chatting and goes through the same service functions the REST API uses, so the
person's project role, the workflow guards and the versioning apply unchanged; readers are not even offered the
changing tools. Tools that change data are **never executed by the model**: the server runs them in a savepoint
that is rolled back, keeps them as pending proposals with that exact preview, and applies them only after the
person confirms. Applied changes are ordinary changes — ordinary item versions with a change note, ordinary audit
entries by that person — plus an `assistant.asked` and `assistant.applied` entry that records what was asked and
proposed. The model provider sits behind one module (`assistant/llm.py`, Azure OpenAI today) and the installation
stays fully usable with the assistant switched off.

**Consequences.** + Answers are grounded in the project and cannot leak across permissions; a wrong proposal costs
a click, not a data repair; nothing in the product depends on a particular model. + The same tools serve a future
provider, and the browser tests can run against a stand-in. − Every question costs several model calls and holds a
database connection while they run; a bulk change is many proposals rather than one, which is slower by design. −
The assistant is only as good as its tool set: anything without a tool (documents, baselines, plans, BOM) is
invisible to it, and adding a tool is a deliberate step, not a configuration switch.
