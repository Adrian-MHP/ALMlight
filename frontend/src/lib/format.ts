import { intlLocale, tx } from "@/lib/i18n";

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleDateString(intlLocale(), { year: "numeric", month: "short", day: "2-digit" });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(intlLocale(), { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "–";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return tx("just now");
  if (diff < 3600) return tx("{Math} min ago", { Math: Math.floor(diff / 60) });
  if (diff < 86400) return tx("{Math} h ago", { Math: Math.floor(diff / 3600) });
  if (diff < 86400 * 7) return tx("{Math} d ago", { Math: Math.floor(diff / 86400) });
  return fmtDate(iso);
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "–";
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "boolean") return v ? tx("Yes") : tx("No");
  return String(v);
}
