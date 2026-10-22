import { useMemo } from "react";
import DOMPurify from "dompurify";
import { Text } from "@mantine/core";
import { useNavigate, useParams } from "react-router-dom";

// Mirrors the server's canonical HTML (core/richtext.py); diffs add <ins>/<del>.
const ALLOWED_TAGS = ["p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "u", "s", "sub", "sup", "code",
  "mark", "a", "ul", "ol", "li", "blockquote", "pre", "hr", "table", "tbody", "tr", "th", "td", "img", "span", "ins",
  "del"];
const ALLOWED_ATTR = ["href", "src", "alt", "title", "width", "height", "colspan", "rowspan", "start", "style",
  "data-type", "data-key"];

let hooked = false;
function purifier() {
  if (!hooked) {
    hooked = true;
    DOMPurify.addHook("afterSanitizeAttributes", (node) => {
      const el = node as Element;
      if (el.tagName === "A" && el.getAttribute("href")) {
        const href = el.getAttribute("href") ?? "";
        if (/^https?:|^mailto:/i.test(href)) {
          el.setAttribute("target", "_blank");
          el.setAttribute("rel", "noopener noreferrer");
        }
      }
      if (el.tagName === "IMG") {
        const src = el.getAttribute("src") ?? "";
        if (!/^\/api\/v1\/images\/[0-9a-f]{64}$/.test(src)) el.removeAttribute("src");
        el.setAttribute("loading", "lazy");
      }
      if (el.hasAttribute("style")) {
        const align = /text-align:\s*(center|right|justify)/.exec(el.getAttribute("style") ?? "");
        if (align) el.setAttribute("style", `text-align: ${align[1]}`);
        else el.removeAttribute("style");
      }
    });
  }
  return DOMPurify;
}

const cache = new Map<string, string>();

export function sanitize(html: string): string {
  const hit = cache.get(html);
  if (hit !== undefined) return hit;
  const clean = purifier().sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR, ALLOW_DATA_ATTR: false });
  if (cache.size > 5000) cache.clear();
  cache.set(html, clean);
  return clean;
}

export function htmlToText(html: string): string {
  const div = document.createElement("div");
  div.innerHTML = sanitize(html);
  return (div.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** Renders stored rich text (sanitised again in the browser). Item references navigate to the item. */
export function RichText({ html, empty = "No description.", className, projectKey, testId }: {
  html: string | null | undefined; empty?: string; className?: string; projectKey?: string; testId?: string;
}) {
  const navigate = useNavigate();
  const params = useParams();
  const project = projectKey ?? params.projectKey;
  const clean = useMemo(() => (html ? sanitize(html) : ""), [html]);
  if (!clean.trim()) {
    return empty ? <Text c="dimmed" size="sm" fs="italic">{empty}</Text> : null;
  }
  return (
    <div className={`rich-text ${className ?? ""}`} data-testid={testId}
      onClick={(e) => {
        const ref = (e.target as HTMLElement).closest('span[data-type="item-ref"]');
        if (ref && project) {
          e.preventDefault();
          navigate(`/p/${project}/items/${ref.getAttribute("data-key")}`);
        }
      }}
      dangerouslySetInnerHTML={{ __html: clean }} />
  );
}

/** A word-level difference (``<ins>``/``<del>``) — ``side`` shows only the old or only the new text. */
export function RichDiff({ html, side = "both" }: { html: string; side?: "both" | "old" | "new" }) {
  return <RichText html={html} empty="" className={`rich-diff rich-diff-${side}`} />;
}
