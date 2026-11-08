import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActionIcon, Alert, Badge, Button, Card, Group, Menu, Modal, Stack, Text, Textarea, Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertTriangle, IconArrowLeft, IconDeviceFloppy, IconDownload, IconLayoutGrid, IconLink, IconNote,
  IconPlus, IconTrash, IconZoomIn, IconZoomOut,
} from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, downloadUrl } from "@/api/client";
import { pk, useProjectMutation } from "@/api/hooks";
import type { Diagram, DiagramEdge, DiagramNode, DiagramRelated } from "@/api/types";
import { ItemPicker } from "@/components/ItemPicker";
import { tx } from "@/lib/i18n";
import { useProjectCtx } from "./ProjectLayout";
import { viewpointLabel } from "./ArchitecturePage";

/** The same colours the server draws the SVG with, so the canvas and the exported picture match. */
const FILL: Record<string, string> = {
  requirement: "#eef2fb", architecture: "#e8f5f6", verification: "#eaf7ef", change: "#fdf1e7",
  risk: "#fdecec", variability: "#f6edfa", planning: "#e9f4fa", document: "#f1f3f5", other: "#f1f3f5",
};
const STROKE: Record<string, string> = {
  requirement: "#4c6ef5", architecture: "#0f8a94", verification: "#2f9e68", change: "#e8823a",
  risk: "#d9534f", variability: "#9c5fb5", planning: "#3a92c4", document: "#868e96", other: "#868e96",
};

type Point = { x: number; y: number };

/** Where a straight line between two boxes meets their edges. */
function edgePoints(a: DiagramNode, b: DiagramNode) {
  const ax = a.x + a.w / 2, ay = a.y + a.h / 2, bx = b.x + b.w / 2, by = b.y + b.h / 2;
  const dx = bx - ax, dy = by - ay;
  if (!dx && !dy) return { x1: ax, y1: ay, x2: bx, y2: by };
  const cut = (cx: number, cy: number, n: DiagramNode, sx: number, sy: number) => {
    const s = Math.min(sx ? (n.w / 2 + 2) / Math.abs(sx) : 1e9, sy ? (n.h / 2 + 2) / Math.abs(sy) : 1e9);
    return { x: cx + sx * s, y: cy + sy * s };
  };
  const from = cut(ax, ay, a, dx, dy), to = cut(bx, by, b, -dx, -dy);
  return { x1: from.x, y1: from.y, x2: to.x, y2: to.y };
}

/** How far each edge is bowed aside, so two relationships between the same pair stay apart. */
function parallel(edges: DiagramEdge[]): Record<string, number> {
  const groups: Record<string, string[]> = {};
  for (const e of edges) (groups[[e.from, e.to].sort().join("|")] ??= []).push(e.id);
  const out: Record<string, number> = {};
  for (const members of Object.values(groups)) {
    members.forEach((id, i) => { out[id] = (i - (members.length - 1) / 2) * 26; });
  }
  return out;
}

function control(x1: number, y1: number, x2: number, y2: number, bow: number) {
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  if (!bow) return { cx: mx, cy: my };
  const dx = x2 - x1, dy = y2 - y1, length = Math.hypot(dx, dy) || 1;
  return { cx: mx - (dy / length) * bow, cy: my + (dx / length) * bow };
}

function wrap(text: string, width: number, lines: number): string[] {
  const perLine = Math.max(8, Math.floor(width / 6.4));
  const out: string[] = [];
  for (const word of (text || "").split(/\s+/).filter(Boolean)) {
    if (out.length && out[out.length - 1].length + 1 + word.length <= perLine) out[out.length - 1] += ` ${word}`;
    else if (out.length < lines) out.push(word.slice(0, perLine));
    else { out[out.length - 1] = `${out[out.length - 1].slice(0, perLine - 1)}…`; break; }
  }
  return out.length ? out : [""];
}

/** The canvas: elements of the project with their relationships, placed by hand or arranged automatically. */
export function DiagramEditor() {
  const { key, can, model } = useProjectCtx();
  const { diagramKey = "" } = useParams();
  const qc = useQueryClient();
  const base = `/projects/${key}/diagrams/${diagramKey}`;
  const svgRef = useRef<SVGSVGElement>(null);
  const query = useQuery<Diagram>({ queryKey: pk(key, "diagram", diagramKey), queryFn: () => api.get(base) });
  const diagram = query.data;

  const [nodes, setNodes] = useState<DiagramNode[]>([]);
  const [dirty, setDirty] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [connectTo, setConnectTo] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [view, setView] = useState({ x: 20, y: 20, zoom: 1 });
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const pan = useRef<Point | null>(null);

  useEffect(() => { if (diagram) { setNodes(diagram.nodes); setDirty(false); } }, [diagram]);

  const edges = diagram?.edges ?? [];
  const byId = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);
  const bows = useMemo(() => parallel(edges), [edges]);
  const editable = can("contributor") && !diagram?.frozen;
  // the canvas as the server stores it; kept in a ref so a request always sends what is on screen now
  const content = useCallback(() => ({
    nodes: nodes.map((n) => (n.kind === "note"
      ? { id: n.id, kind: "note", text: n.text ?? "", x: n.x, y: n.y, w: n.w, h: n.h }
      : { id: n.id, item: n.item, x: n.x, y: n.y, w: n.w, h: n.h })),
    edges: edges.map((e) => ({ id: e.id, from: e.from, to: e.to, ...(e.link ? { link: e.link } : {}) })),
  }), [nodes, edges]);
  const latest = useRef(content);
  latest.current = content;

  const applied = (d: Diagram) => { qc.setQueryData(pk(key, "diagram", diagramKey), d); qc.invalidateQueries({ queryKey: pk(key, "diagrams") }); };
  const act = useProjectMutation(key, (v: { path: string; body?: Record<string, unknown> }) =>
    api.post<Diagram>(`${base}${v.path}`, { ...latest.current(), ...(v.body ?? {}) }), { onSuccess: applied });
  const save = useProjectMutation(key, () =>
    api.put<Diagram>(base, { ...latest.current(), expected_version: diagram?.version_no }), {
    success: tx("Diagram saved"), onSuccess: applied,
  });

  // --- pointer handling: drag a node, pan the canvas, zoom with the wheel
  const toWorld = (e: { clientX: number; clientY: number }): Point => {
    const box = svgRef.current?.getBoundingClientRect();
    return { x: ((e.clientX - (box?.left ?? 0)) - view.x) / view.zoom, y: ((e.clientY - (box?.top ?? 0)) - view.y) / view.zoom };
  };
  const onNodeDown = (e: React.PointerEvent, n: DiagramNode) => {
    e.stopPropagation();
    setSelected(n.id);
    if (connectFrom && connectFrom !== n.id) { setConnectTo(n.id); return; }
    if (!editable) return;
    const p = toWorld(e);
    drag.current = { id: n.id, dx: p.x - n.x, dy: p.y - n.y };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    if (drag.current) {
      const p = toWorld(e);
      const { id, dx, dy } = drag.current;
      setNodes((all) => all.map((n) => (n.id === id ? { ...n, x: Math.round(p.x - dx), y: Math.round(p.y - dy) } : n)));
      setDirty(true);
    } else if (pan.current) {
      setView((v) => ({ ...v, x: v.x + e.movementX, y: v.y + e.movementY }));
    }
  };
  const stop = () => { drag.current = null; pan.current = null; };
  const zoom = (factor: number) => setView((v) => ({ ...v, zoom: Math.min(2.5, Math.max(0.3, v.zoom * factor)) }));

  const connect = (type: string) => {
    act.mutate({ path: "/connect", body: { source: connectFrom, target: connectTo, type } });
    setConnectFrom(null); setConnectTo(null);
  };
  const allowed = useMemo(() => {
    const a = byId[connectFrom ?? ""], b = byId[connectTo ?? ""];
    return a?.type && b?.type ? model.allowedLinks(a.type, b.type) : [];
  }, [byId, connectFrom, connectTo, model]);
  useEffect(() => {
    if (connectTo && allowed.length === 0) {
      notifications.show({ color: "red", message: tx("The information model allows no relationship between these two.") });
      setConnectFrom(null); setConnectTo(null);
    }
  }, [connectTo, allowed]);

  if (!diagram) return null;
  const node = nodes.find((n) => n.id === selected);
  const size = { w: Math.max(...nodes.map((n) => n.x + n.w), 600) + 80, h: Math.max(...nodes.map((n) => n.y + n.h), 400) + 80 };

  return (
    <Stack gap="xs" style={{ height: "calc(100vh - 110px)" }}>
      <Group justify="space-between" wrap="wrap" gap="xs">
        <Group gap="xs" wrap="nowrap">
          <ActionIcon variant="subtle" component={Link} to={`/p/${key}/architecture`} aria-label={tx("Back")}><IconArrowLeft size={18} /></ActionIcon>
          <div>
            <Group gap={6}>
              <Text fw={600}>{diagram.title}</Text>
              <Badge size="xs" variant="light">{diagram.key}</Badge>
              <Badge size="xs" variant="outline">{diagram.version}</Badge>
              {diagram.frozen && <Badge size="xs" color="orange">{tx("frozen")}</Badge>}
            </Group>
            <Text size="xs" c="dimmed">{viewpointLabel(diagram.viewpoint)}</Text>
          </div>
        </Group>
        <Group gap="xs">
          {editable && (
            <>
              <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setAdding(true)} data-testid="diagram-add">{tx("Add element")}</Button>
              <Button size="xs" variant="default" leftSection={<IconNote size={14} />} onClick={() => setNote("")} data-testid="diagram-note">{tx("Note")}</Button>
              <Button size="xs" variant="default" leftSection={<IconLayoutGrid size={14} />}
                onClick={() => act.mutate({ path: "/layout" })} loading={act.isPending} data-testid="diagram-layout">{tx("Arrange")}</Button>
              <Button size="xs" variant={dirty ? "filled" : "default"} leftSection={<IconDeviceFloppy size={14} />}
                onClick={() => save.mutate(undefined)} disabled={!dirty} loading={save.isPending} data-testid="diagram-save">
                {dirty ? tx("Save") : tx("Saved")}
              </Button>
            </>
          )}
          <ActionIcon.Group>
            <ActionIcon variant="default" onClick={() => zoom(1 / 1.2)} aria-label={tx("Zoom out")}><IconZoomOut size={16} /></ActionIcon>
            <ActionIcon variant="default" onClick={() => zoom(1.2)} aria-label={tx("Zoom in")}><IconZoomIn size={16} /></ActionIcon>
          </ActionIcon.Group>
          <Tooltip label={tx("Download as SVG")}>
            <ActionIcon variant="default" component="a" href={downloadUrl(`${base}.svg`)} aria-label={tx("Download as SVG")}><IconDownload size={16} /></ActionIcon>
          </Tooltip>
        </Group>
      </Group>

      {diagram.stale.missing_items.length > 0 && (
        <Alert color="orange" p="xs" icon={<IconAlertTriangle size={16} />} data-testid="diagram-stale">
          <Text size="xs">{tx("These items were deleted and are only shown as a placeholder: {keys}", { keys: diagram.stale.missing_items.join(", ") })}</Text>
        </Alert>
      )}
      {connectFrom && <Alert color="teal" p="xs" data-testid="diagram-connecting"><Text size="xs">{tx("Click the element this one points at. Esc cancels.")}</Text></Alert>}

      <Group align="stretch" gap="xs" style={{ flex: 1, minHeight: 0 }}>
        <Card withBorder p={0} style={{ flex: 1, overflow: "hidden" }}>
          <svg ref={svgRef} width="100%" height="100%" data-testid="diagram-canvas" tabIndex={0}
            style={{ touchAction: "none", cursor: pan.current ? "grabbing" : "default", display: "block" }}
            onPointerDown={(e) => { pan.current = { x: e.clientX, y: e.clientY }; setSelected(null); }}
            onPointerMove={onMove} onPointerUp={stop} onPointerLeave={stop}
            onKeyDown={(e) => { if (e.key === "Escape") { setConnectFrom(null); setConnectTo(null); } }}
            onWheel={(e) => zoom(e.deltaY < 0 ? 1.1 : 1 / 1.1)}>
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#6b7a8c" />
              </marker>
            </defs>
            <g transform={`translate(${view.x},${view.y}) scale(${view.zoom})`}>
              <rect x={-2000} y={-2000} width={size.w + 4000} height={size.h + 4000} fill="transparent" />
              {edges.map((e) => {
                const a = byId[e.from], b = byId[e.to];
                if (!a || !b) return null;
                const { x1, y1, x2, y2 } = edgePoints(a, b);
                const { cx, cy } = control(x1, y1, x2, y2, bows[e.id] ?? 0);
                return (
                  <g key={e.id} data-testid={`edge-${e.type ?? "x"}`}>
                    <path d={`M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`} fill="none"
                      stroke={e.suspect ? "#d9534f" : "#6b7a8c"} strokeWidth={1.3} markerEnd="url(#arrow)" />
                    {e.label && (
                      <text x={(x1 + 2 * cx + x2) / 4} y={(y1 + 2 * cy + y2) / 4 + 3} fontSize={10} fill="#6b7a8c" textAnchor="middle"
                        style={{ paintOrder: "stroke", stroke: "var(--mantine-color-body)", strokeWidth: 4 }}>{e.label}</text>
                    )}
                  </g>
                );
              })}
              {nodes.map((n) => (
                <Node key={n.id} node={n} selected={selected === n.id} connecting={connectFrom === n.id}
                  onDown={(e) => onNodeDown(e, n)} />
              ))}
            </g>
          </svg>
        </Card>
        <Card withBorder p="sm" w={280} style={{ overflowY: "auto" }} data-testid="diagram-panel">
          {!node && <Text size="sm" c="dimmed">{tx("Pick an element to see what it is and what you can do with it. Drag to move, drag the background to pan.")}</Text>}
          {node?.kind === "note" && <Text size="sm">{node.text}</Text>}
          {node && node.kind !== "note" && (
            <Stack gap="xs">
              <div>
                <Text size="xs" c="dimmed">{node.type_label}</Text>
                <Text fw={600} size="sm">{node.title ?? tx("(deleted)")}</Text>
                <Group gap={6} mt={4}>
                  <Badge size="xs" variant="light">{node.item}</Badge>
                  {node.state && <Badge size="xs" variant="outline">{node.state}</Badge>}
                  {node.version && <Badge size="xs" variant="outline">{node.version}</Badge>}
                </Group>
              </div>
              {!node.missing && <Button size="xs" variant="light" component={Link} to={`/p/${key}/items/${node.item}`}>{tx("Open item")}</Button>}
              {editable && (
                <>
                  <Button size="xs" variant="default" leftSection={<IconLink size={14} />} data-testid="diagram-connect"
                    onClick={() => { setConnectFrom(node.id); setConnectTo(null); }}>{tx("Draw relationship")}</Button>
                  <Button size="xs" variant="default" color="red" leftSection={<IconTrash size={14} />} data-testid="diagram-remove"
                    onClick={() => act.mutate({ path: `/nodes/${node.id}/remove` })}>{tx("Remove from diagram")}</Button>
                  <Text size="xs" c="dimmed">{tx("The item itself stays in the project.")}</Text>
                </>
              )}
              <EdgeList edges={edges.filter((e) => e.from === node.id || e.to === node.id)} nodes={byId} node={node}
                editable={editable} onRemove={(edge, deleteLink) => act.mutate({ path: `/edges/${edge}/remove`, body: { delete_link: deleteLink } })} />
            </Stack>
          )}
        </Card>
      </Group>

      {adding && <AddElements onClose={() => setAdding(false)} onAdd={(keys) => { act.mutate({ path: "/items", body: { keys } }); setAdding(false); }} />}
      {note !== null && (
        <Modal opened onClose={() => setNote(null)} title={tx("Note")}>
          <Textarea autosize minRows={3} value={note} onChange={(e) => setNote(e.currentTarget.value)} data-testid="note-text" />
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={() => setNote(null)}>{tx("Cancel")}</Button>
            <Button disabled={!note.trim()} onClick={() => { act.mutate({ path: "/notes", body: { text: note } }); setNote(null); }}>{tx("Add")}</Button>
          </Group>
        </Modal>
      )}
      {connectTo && allowed.length > 0 && (
        <Modal opened onClose={() => { setConnectFrom(null); setConnectTo(null); }} title={tx("Which relationship?")}>
          <Text size="sm" mb="sm">
            {byId[connectFrom ?? ""]?.item} → {byId[connectTo]?.item}
          </Text>
          <Stack gap="xs">
            {allowed.map((option) => (
              <Button key={option.value} variant="default" justify="flex-start" onClick={() => connect(option.value)}
                data-testid={`connect-${option.value}`}>{option.label}</Button>
            ))}
          </Stack>
        </Modal>
      )}
    </Stack>
  );
}

function Node({ node, selected, connecting, onDown }: {
  node: DiagramNode; selected: boolean; connecting: boolean; onDown: (e: React.PointerEvent) => void;
}) {
  const category = node.category ?? "other";
  const stroke = node.missing ? "#d9534f" : connecting ? "#0f8a94" : STROKE[category] ?? STROKE.other;
  const fill = node.kind === "note" ? "#fffbe6" : node.missing ? "#fdecec" : FILL[category] ?? FILL.other;
  return (
    <g onPointerDown={onDown} style={{ cursor: "move" }} data-testid={`node-${node.item ?? node.id}`}>
      <rect x={node.x} y={node.y} width={node.w} height={node.h} rx={5} fill={fill}
        stroke={node.kind === "note" ? "#e0c97f" : stroke} strokeWidth={selected || connecting ? 2.4 : 1.2} />
      {node.kind === "note"
        ? wrap(node.text ?? "", node.w - 16, 4).map((line, i) => (
          <text key={i} x={node.x + 8} y={node.y + 20 + i * 14} fontSize={11} fill="#1f2d3d">{line}</text>))
        : (
          <>
            <text x={node.x + 10} y={node.y + 17} fontSize={10} fontWeight={600} fill={stroke}>{node.type_label}</text>
            <text x={node.x + node.w - 10} y={node.y + 17} fontSize={10} fill="#6b7a8c" textAnchor="end">{node.item}</text>
            {wrap(node.title ?? tx("(deleted)"), node.w - 20, 2).map((line, i) => (
              <text key={i} x={node.x + 10} y={node.y + 36 + i * 15} fontSize={11.5} fill="#1f2d3d">{line}</text>))}
            {node.state && <text x={node.x + 10} y={node.y + node.h - 9} fontSize={9.5} fill="#6b7a8c">{node.state}</text>}
          </>
        )}
    </g>
  );
}

function EdgeList({ edges, nodes, node, editable, onRemove }: {
  edges: DiagramEdge[]; nodes: Record<string, DiagramNode>; node: DiagramNode; editable: boolean;
  onRemove: (edge: string, deleteLink: boolean) => void;
}) {
  if (!edges.length) return null;
  return (
    <Stack gap={4} mt="xs">
      <Text size="xs" fw={600}>{tx("Relationships")}</Text>
      {edges.map((e) => {
        const other = nodes[e.from === node.id ? e.to : e.from];
        return (
          <Group key={e.id} gap={4} wrap="nowrap" justify="space-between">
            <Text size="xs" lineClamp={1}>
              {e.from === node.id ? "→" : "←"} {e.label} {other?.item}
            </Text>
            {editable && (
              <Menu position="bottom-end">
                <Menu.Target><ActionIcon size="xs" variant="subtle" aria-label={tx("Relationship")}><IconTrash size={12} /></ActionIcon></Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item onClick={() => onRemove(e.id, false)}>{tx("Remove from diagram")}</Menu.Item>
                  <Menu.Item color="red" onClick={() => onRemove(e.id, true)}>{tx("Delete the link as well")}</Menu.Item>
                </Menu.Dropdown>
              </Menu>
            )}
          </Group>
        );
      })}
    </Stack>
  );
}

function AddElements({ onClose, onAdd }: { onClose: () => void; onAdd: (keys: string[]) => void }) {
  const { key } = useProjectCtx();
  const { diagramKey = "" } = useParams();
  const [picked, setPicked] = useState<string | null>(null);
  const related = useQuery<DiagramRelated[]>({
    queryKey: pk(key, "diagram", diagramKey, "related"),
    queryFn: () => api.get(`/projects/${key}/diagrams/${diagramKey}/related`),
  }).data ?? [];
  return (
    <Modal opened onClose={onClose} title={tx("Add element")} size="lg">
      <Stack>
        <ItemPicker value={picked} onChange={(v) => setPicked(v)} label={tx("Any item of the project")}
          testId="item-picker" w={520} />
        <Group justify="flex-end">
          <Button disabled={!picked} onClick={() => picked && onAdd([picked])} data-testid="add-picked">{tx("Add")}</Button>
        </Group>
        {related.length > 0 && (
          <>
            <Text size="sm" fw={600}>{tx("Linked to what the diagram already shows")}</Text>
            <Stack gap={4}>
              {related.map((r) => (
                <Group key={r.key} justify="space-between" wrap="nowrap">
                  <Text size="sm" lineClamp={1}>
                    <Badge size="xs" variant="light" mr={6}>{r.key}</Badge>{r.title}
                    <Text span size="xs" c="dimmed"> · {r.via}</Text>
                  </Text>
                  <Button size="compact-xs" variant="default" onClick={() => onAdd([r.key])}
                    data-testid={`add-related-${r.key}`}>{tx("Add")}</Button>
                </Group>
              ))}
            </Stack>
          </>
        )}
      </Stack>
    </Modal>
  );
}
