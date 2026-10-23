import type { FieldDef } from "@/api/types";
import { tx } from "@/lib/i18n";

/**
 * Preview of computed fields while a form is edited — the same small language as the server
 * (numbers, field names, + - * / // %, parentheses, min/max/abs/round). The server stays authoritative:
 * it recomputes on save, so a preview only has to be right for the common case.
 */
const FUNCTIONS: Record<string, (...a: number[]) => number> = {
  min: Math.min, max: Math.max, abs: Math.abs, round: (v: number, nd = 0) => Math.round(v * 10 ** nd) / 10 ** nd,
};

class Missing extends Error {}

export function evalFormula(expr: string, values: Record<string, unknown>): number | null {
  const tokens = expr.match(/\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*|\/\/|[-+*/%(),]/g) ?? [];
  let i = 0;
  const peek = () => tokens[i];
  const take = (t?: string) => {
    const tok = tokens[i++];
    if (t !== undefined && tok !== t) throw new Error(tx("expected {t}", { t: t }));
    return tok;
  };
  const primary = (): number => {
    const tok = take();
    if (tok === undefined) throw new Error("end");
    if (tok === "(") { const v = sum(); take(")"); return v; }
    if (tok === "-") return -primary();
    if (tok === "+") return primary();
    if (/^\d/.test(tok)) return Number(tok);
    if (peek() === "(" && FUNCTIONS[tok]) {
      take("(");
      const args: number[] = [];
      if (peek() !== ")") { args.push(sum()); while (peek() === ",") { take(","); args.push(sum()); } }
      take(")");
      return FUNCTIONS[tok](...args);
    }
    const v = values[tok];
    if (typeof v !== "number" || Number.isNaN(v)) throw new Missing(tok);
    return v;
  };
  const product = (): number => {
    let v = primary();
    while (["*", "/", "//", "%"].includes(peek() ?? "")) {
      const op = take(), r = primary();
      if ((op === "/" || op === "//" || op === "%") && r === 0) throw new Missing(tx("division by zero"));
      v = op === "*" ? v * r : op === "/" ? v / r : op === "//" ? Math.floor(v / r) : v - r * Math.floor(v / r);
    }
    return v;
  };
  const sum = (): number => {
    let v = product();
    while (peek() === "+" || peek() === "-") v = take() === "+" ? v + product() : v - product();
    return v;
  };
  try {
    const v = sum();
    return i === tokens.length && Number.isFinite(v) ? v : null;
  } catch {
    return null;
  }
}

/** The values with every formula and classification field recomputed, in definition order. */
export function withComputed(defs: FieldDef[], values: Record<string, unknown>): Record<string, unknown> {
  if (!defs.some((d) => d.formula || d.classify)) return values;
  const out: Record<string, unknown> = { ...values };
  for (const d of defs) {
    if (d.formula) {
      const v = evalFormula(d.formula, out);
      if (v === null) delete out[d.key];
      else out[d.key] = d.type === "integer" ? Math.round(v) : Math.round(v * 1e6) / 1e6;
    } else if (d.classify) {
      const base = out[d.classify.field];
      let level: string | undefined;
      if (typeof base === "number") {
        for (const [threshold, option] of [...d.classify.bands].sort((a, b) => a[0] - b[0])) if (base >= threshold) level = option;
      }
      if (level === undefined) delete out[d.key];
      else out[d.key] = level;
    }
  }
  return out;
}
