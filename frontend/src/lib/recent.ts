// Recently opened objects (per browser), shown on the home page like the "recent" lists of PLM workspaces.
import { useCallback, useEffect, useState } from "react";

export interface RecentEntry { project: string; key: string; title: string; kind: "item" | "document"; ts: number }
const KEY = "alm-recent";
const MAX = 10;

function read(): RecentEntry[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as RecentEntry[];
  } catch {
    return [];
  }
}

export function remember(entry: Omit<RecentEntry, "ts">) {
  try {
    const list = read().filter((e) => !(e.project === entry.project && e.key === entry.key && e.kind === entry.kind));
    localStorage.setItem(KEY, JSON.stringify([{ ...entry, ts: Date.now() }, ...list].slice(0, MAX)));
  } catch {
    /* storage unavailable */
  }
}

export function useRemember(entry: Omit<RecentEntry, "ts"> | null) {
  const sig = entry ? `${entry.project}:${entry.kind}:${entry.key}:${entry.title}` : "";
  useEffect(() => {
    if (entry) remember(entry);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);
}

export function useRecent(): [RecentEntry[], () => void] {
  const [list, setList] = useState<RecentEntry[]>(() => read());
  useEffect(() => setList(read()), []);
  const clear = useCallback(() => {
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
    setList([]);
  }, []);
  return [list, clear];
}
