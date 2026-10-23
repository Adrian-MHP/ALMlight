# 16 Languages: English and German user interface (0.7)

Ariadne ships with an English and a German user interface. The language covers everything a user reads: the
interface texts, the labels of the project's information model (item types, fields, values, states, transitions,
link types), messages from the server (validation, permissions, conflicts), the activity and history texts,
notifications and e-mail digests, the document view, and Word/PDF exports. Dates and numbers follow the language.

## 16.1 Choosing the language

- **First visit**: the browser's language (German browsers get the German interface).
- **User menu → Language** or **Account → Language**: the choice is saved with the user account, so it follows the
  user to every browser and device, and the server uses it for e-mail digests and exports (also for downloads opened
  from links). Switching reloads the page.
- Requests without a user choice use the browser's `Accept-Language`; API clients can send `Accept-Language: de`.

## 16.2 How it is built

| Part | Source of the texts | Where the translation happens |
|---|---|---|
| Interface texts (≈ 1,440) | English texts in the code are the keys of `frontend/src/locales/de.ts` | In the browser (`tx()`) |
| Model labels | `translations` in the information model (template or project configuration) | In the browser (the model is localised when a project opens) and on the server (document view, exports) |
| Server messages, activity, notifications | English templates in `backend/almlight/locales/de.json` (`messages`) | On the server per request; stored texts stay English and are translated when shown |
| E-mail digests, Word/PDF texts | `texts` in `backend/almlight/locales/de.json` | On the server, in the recipient's or requester's language |

Stored data never changes language: audit entries, notifications and item content stay as written, so the audit
trail and hash chain are unaffected and the same entry reads in English or German depending on the reader.

## 16.3 Model labels per customer

The labels of an information model are configuration, like the model itself. The shipped template carries German
labels for all its types, fields, values, states, transitions and links:

```yaml
translations:
  de:
    "System Requirement": "Systemanforderung"
    "Submit for review": "Zur Prüfung einreichen"
    "verified by": "verifiziert durch"
```

A tailored model adds or overrides entries for its own labels (*Settings → Information model*, JSON). Labels
without a translation are shown in English. *Template updates* offer the template's translations for labels the
project does not translate yet and never overwrite the project's own translations.

## 16.4 Quality gates

- `npm run build` fails when an interface text has no German translation (`scripts/i18n-check.mjs`); placeholders
  (`{name}`) must match.
- A backend test scans the source for every exception message, audit summary and server text and fails when one has
  no German version or a placeholder count differs.
- The browser suite runs a German pass (phone, all main pages) and a scripted switch of the language.

## 16.5 Adding a language

1. Copy `frontend/src/locales/de.ts` to e.g. `fr.ts`, translate the values, and register it in `lib/i18n.ts`
   (`LOCALES`, `DICTS`).
2. Copy `backend/almlight/locales/de.json` to `fr.json`, translate, and add `fr` to `SUPPORTED` in
   `almlight/core/i18n.py` and to the allowed values of `PUT /auth/me/locale`.
3. Add `translations: fr:` to the information model.
4. Run `npm run build` and the backend tests — both list what is still missing.
