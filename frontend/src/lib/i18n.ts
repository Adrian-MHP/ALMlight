// User interface language. English texts in the source are the keys; a dictionary per language translates them.
// The language is read once at start (browser storage, else the browser language) and a change reloads the page,
// so texts in module-level constants are translated as well.

import { de } from "@/locales/de";

export type Locale = "en" | "de";
export const LOCALES: { value: Locale; label: string }[] = [{ value: "en", label: "English" }, { value: "de", label: "Deutsch" }];
const STORAGE_KEY = "ariadne.locale";
const DICTS: Record<Locale, Record<string, string>> = { en: {}, de };

function initial(): Locale {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "en" || v === "de") return v;
  } catch { /* storage blocked */ }
  return typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("de") ? "de" : "en";
}

let current: Locale = initial();
if (typeof document !== "undefined") document.documentElement.lang = current;

export function locale(): Locale {
  return current;
}

/** Decimal separator for number inputs (3,5 in German). */
export function decimalSep(): string {
  return current === "de" ? "," : ".";
}

/** BCP 47 tag for dates and numbers. */
export function intlLocale(): string {
  return current === "de" ? "de-DE" : "en-GB";
}

function fill(s: string, vars?: Record<string, unknown>): string {
  return vars ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k] ?? "") : m)) : s;
}

/** Translate an interface text; ``{name}`` placeholders are filled from ``vars``. */
export function tx(en: string, vars?: Record<string, unknown>): string {
  return fill(DICTS[current][en] ?? en, vars);
}

let modelDict: Record<string, string> = {};

/** Labels of the project's information model (types, fields, states, transitions, links) are tailored per customer:
 *  the model's own translations first, then the interface dictionary. */
export function setModelTranslations(map: Record<string, string> | undefined): void {
  modelDict = map ?? {};
}

export function tm(label: string): string;
export function tm(label: string | null | undefined): string | null | undefined;
export function tm(label: string | null | undefined): string | null | undefined {
  if (!label || current === "en") return label;
  return modelDict[label] ?? DICTS[current][label] ?? label;
}

/** Switch the language (the page reloads so every text follows). */
export function setLocale(l: Locale, reload = true): void {
  try { localStorage.setItem(STORAGE_KEY, l); } catch { /* storage blocked */ }
  if (l === current) return;
  current = l;
  if (reload) window.location.reload();
}

export function storedLocale(): Locale | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "en" || v === "de" ? v : null;
  } catch {
    return null;
  }
}

/** Choose the language: saved with the user on the server (follows them to other devices), then the page reloads. */
export async function chooseLanguage(l: Locale, save: (l: Locale) => Promise<unknown>): Promise<void> {
  try { await save(l); } catch { /* still switch locally */ }
  setLocale(l);
}
