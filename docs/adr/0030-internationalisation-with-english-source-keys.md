# ADR-0030 Internationalisation: English source texts as keys, server-side translation of server texts

**Context.** SME customers in German-speaking countries expect a German interface, German model labels and German
messages; customer-specific information models have their own labels. Stored data (audit trail, notifications) must
not change with the reader's language — the audit trail is hash-chained.

**Decision.** Interface texts are written in English in the code and wrapped in `tx()`; the English text is the key
of a per-language dictionary (no separate key names to keep in sync), placeholders are named (`{name}`). Model labels
are configuration: `translations.<lang>` in the information model, tailorable per project and offered by template
updates without overwriting the project's own entries. The server translates what it produces — messages,
activity and history texts, notification titles, e-mail digests, document views and exports — from one catalogue
(`locales/<lang>.json`) at the time it is read, in the language of the user (saved with the account) or of the
request (`Accept-Language`). A build check and a backend test fail when a text has no translation.

**Consequences.** + One language setting covers the browser, e-mails and downloads; stored records stay unchanged.
+ Adding a language is adding dictionaries. − Interface texts written as sentence fragments around values translate
less naturally; new texts must be added to the dictionaries (enforced by the checks). − Messages of third-party
libraries (e.g. request validation details) stay English.
