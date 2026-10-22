// One live editing session per item: a Yjs document synchronised with the server room over WebSockets.
//
// Start state: every client builds the *same* seed (title + text of the item version it loaded) with a client
// id derived from the item's content hash, so seeds from several clients are identical and merge into one.
import { useEffect, useRef, useState } from "react";
import * as Y from "yjs";
import { WebsocketProvider } from "y-websocket";
import { generateJSON, getSchema } from "@tiptap/core";
import { prosemirrorJSONToYXmlFragment } from "@tiptap/y-tiptap";
import { bodyExtensions, titleExtensions } from "@/components/rich/extensions";

export interface LiveTarget { id: string; key: string; title: string; description: string; content_hash: string }
export interface Participant { id: string; name: string; color: string; canWrite: boolean; clientIds: number[] }
export type LiveStatus = "connecting" | "connected" | "disconnected" | "error";

let bodySchema: ReturnType<typeof getSchema> | null = null;
let titleSchema: ReturnType<typeof getSchema> | null = null;

export function wsBase(): string {
  return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
}

export function seedClientId(hash: string): number {
  return (parseInt(hash.slice(0, 8), 16) >>> 0) || 1;
}

/** Apply the deterministic start state if the shared document is still empty. */
export function seedIfEmpty(doc: Y.Doc, target: LiveTarget): boolean {
  const body = doc.getXmlFragment("body");
  const title = doc.getXmlFragment("title");
  if (body.length > 0 || title.length > 0) return false;
  bodySchema ??= getSchema(bodyExtensions());
  titleSchema ??= getSchema(titleExtensions());
  const seed = new Y.Doc();
  seed.clientID = seedClientId(target.content_hash);
  const titleJson = { type: "doc", content: [{ type: "paragraph", content: target.title ? [{ type: "text", text: target.title }] : [] }] };
  prosemirrorJSONToYXmlFragment(titleSchema, titleJson, seed.getXmlFragment("title"));
  const bodyJson = generateJSON(target.description || "<p></p>", bodyExtensions());
  prosemirrorJSONToYXmlFragment(bodySchema, bodyJson, seed.getXmlFragment("body"));
  Y.applyUpdate(doc, Y.encodeStateAsUpdate(seed));
  seed.destroy();
  return true;
}

export interface LiveSession {
  doc: Y.Doc;
  provider: WebsocketProvider;
  status: LiveStatus;
  ready: boolean;
  participants: Participant[];
  closed: { code: number; reason: string } | null;
}

/**
 * Connect to the item's live session. ``onReset`` is called when the server restarts the session (the text changed
 * elsewhere or the lifecycle state changed): reload the item, the hook reconnects with the new start state.
 */
export function useLiveSession(target: LiveTarget | null, me: { id: string; name: string } | null,
  onReset: () => void): LiveSession | null {
  const [generation, setGeneration] = useState(0);
  const [pair, setPair] = useState<{ doc: Y.Doc; provider: WebsocketProvider } | null>(null);
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [ready, setReady] = useState(false);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [closed, setClosed] = useState<{ code: number; reason: string } | null>(null);
  const latest = useRef({ target, me, onReset });
  latest.current = { target, me, onReset };
  const id = target?.id;
  const hash = target?.content_hash;
  // After a reset the item is reloaded; reconnect once the new text has arrived (or after a short wait when the
  // text did not change, e.g. a lifecycle change).
  const [resetFrom, setResetFrom] = useState<string | null>(null);
  useEffect(() => {
    if (resetFrom === null) return;
    const go = () => { setResetFrom(null); setGeneration((g) => g + 1); };
    if (hash && hash !== resetFrom) { go(); return; }
    const t = window.setTimeout(go, 1500);
    return () => window.clearTimeout(t);
  }, [resetFrom, hash]);

  useEffect(() => {
    const base = latest.current.target?.content_hash;
    if (!id || !base) return;
    const doc = new Y.Doc();
    const provider = new WebsocketProvider(`${wsBase()}/api/v1/collab/items`, id, doc, {
      params: { base },
      disableBc: true,
      maxBackoffTime: 5000,
      shouldReconnect: (event: CloseEvent) => event.code < 4000,
    } as ConstructorParameters<typeof WebsocketProvider>[3]);
    setReady(false);
    setClosed(null);
    setStatus("connecting");
    setParticipants([]);
    const me = latest.current.me;
    if (me) provider.awareness.setLocalStateField("user", { id: me.id, name: me.name });
    const onStatus = ({ status: s }: { status: string }) => setStatus(s as LiveStatus);
    const onSync = (synced: boolean) => {
      const t = latest.current.target;
      if (!synced || !t) return;
      seedIfEmpty(doc, t);
      setReady(true);
    };
    const onClosed = (event: { code: number; reason: string }) => {
      if (event.code === 4001 || event.code === 4409) {
        latest.current.onReset();
        setResetFrom(base);
      } else {
        setClosed(event);
        setStatus("error");
      }
    };
    const onAwareness = () => {
      const byUser = new Map<string, Participant>();
      provider.awareness.getStates().forEach((state, clientId) => {
        const u = state.user as { id?: string; name?: string; color?: string; canWrite?: boolean } | undefined;
        if (!u?.id) return;
        const p = byUser.get(u.id) ?? { id: u.id, name: u.name ?? "?", color: u.color ?? "#868e96", canWrite: !!u.canWrite, clientIds: [] };
        p.clientIds.push(clientId);
        byUser.set(u.id, p);
      });
      setParticipants(Array.from(byUser.values()).sort((a, b) => a.name.localeCompare(b.name)));
    };
    provider.on("status", onStatus);
    provider.on("sync", onSync);
    provider.on("closed", onClosed);
    provider.awareness.on("change", onAwareness);
    setPair({ doc, provider });
    return () => {
      provider.off("status", onStatus);
      provider.off("sync", onSync);
      provider.off("closed", onClosed);
      provider.awareness.off("change", onAwareness);
      provider.destroy();
      doc.destroy();
      setPair(null);
    };
  }, [id, generation]);

  if (!pair) return null;
  return { ...pair, status, ready, participants, closed };
}
