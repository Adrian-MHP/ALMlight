// Live channel: one WebSocket per tab for change events (pages refresh themselves) and presence (who is where).
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { pk } from "@/api/hooks";
import { wsBase } from "@/collab/session";

export interface PresenceUser {
  conn: number; user_id: string; name: string; color: string; doc: string | null; item: string | null;
  editing: string | null; since: string;
}
export interface ChangeEvent {
  type: "change"; project: string; action: string; summary: string; actor: string; actor_id: string | null;
  entity_id: string | null; related_ids: string[]; ts: string;
}
interface Location { doc?: string | null; item?: string | null; editing?: string | null }
interface LiveApi {
  connected: boolean;
  presence: (project: string) => PresenceUser[];
  setLocation: (project: string, where: Location | null) => void;
  onChange: (fn: (e: ChangeEvent) => void) => () => void;
}

const Ctx = createContext<LiveApi | null>(null);

export function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  const [presence, setPresence] = useState<Record<string, PresenceUser[]>>({});
  const ws = useRef<WebSocket | null>(null);
  const locations = useRef<Record<string, Location>>({});
  const listeners = useRef(new Set<(e: ChangeEvent) => void>());
  const pending = useRef(new Set<string>());
  const timer = useRef<number | null>(null);

  const send = useCallback((msg: object) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(msg));
  }, []);

  useEffect(() => {
    let stopped = false;
    let retry = 0;
    let ping: number | null = null;
    const connect = () => {
      if (stopped) return;
      const sock = new WebSocket(`${wsBase()}/api/v1/live`);
      ws.current = sock;
      sock.onopen = () => {
        retry = 0;
        setConnected(true);
        for (const [project, where] of Object.entries(locations.current)) sock.send(JSON.stringify({ type: "presence", project, ...where }));
        ping = window.setInterval(() => sock.readyState === WebSocket.OPEN && sock.send('{"type":"ping"}'), 25_000);
      };
      sock.onmessage = (ev) => {
        let msg: { type: string; project?: string; users?: PresenceUser[] };
        try { msg = JSON.parse(ev.data); } catch { return; }
        const project = msg.project;
        if (msg.type === "presence" && project) {
          setPresence((p) => ({ ...p, [project]: msg.users ?? [] }));
        } else if (msg.type === "change" && project) {
          listeners.current.forEach((fn) => fn(msg as unknown as ChangeEvent));
          pending.current.add(project);
          if (timer.current === null) {
            timer.current = window.setTimeout(() => {
              timer.current = null;
              pending.current.forEach((key) => qc.invalidateQueries({ queryKey: pk(key) }));
              pending.current.clear();
              qc.invalidateQueries({ queryKey: ["inbox"] });
            }, 400);
          }
        }
      };
      sock.onclose = () => {
        setConnected(false);
        if (ping) window.clearInterval(ping);
        if (ws.current === sock) ws.current = null;
        if (!stopped) window.setTimeout(connect, Math.min(10_000, 500 * 2 ** retry++));
      };
    };
    connect();
    return () => {
      stopped = true;
      if (ping) window.clearInterval(ping);
      ws.current?.close();
    };
  }, [qc]);

  const api = useMemo<LiveApi>(() => ({
    connected,
    presence: (project) => presence[project] ?? [],
    setLocation: (project, where) => {
      const loc = where ?? {};
      locations.current[project] = loc;
      send({ type: "presence", project, ...loc });
    },
    onChange: (fn) => {
      listeners.current.add(fn);
      return () => listeners.current.delete(fn);
    },
  }), [connected, presence, send]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useLive(): LiveApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useLive outside LiveProvider");
  return ctx;
}

/** Report where this tab is (project, document, item, the block being edited) for the presence of others. */
export function usePresenceLocation(project: string | undefined, where: Location) {
  const live = useLive();
  const { doc = null, item = null, editing = null } = where;
  useEffect(() => {
    if (!project) return;
    live.setLocation(project, { doc, item, editing });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, doc, item, editing, live.connected]);
  useEffect(() => () => { if (project) live.setLocation(project, {}); },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [project]);
}
