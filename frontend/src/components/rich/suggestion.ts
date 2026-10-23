// "#" in the editor: search items and insert a reference. A small floating list (no extra UI library).
import { computePosition, flip, offset, shift } from "@floating-ui/dom";
import type { SuggestionOptions, SuggestionProps } from "@tiptap/suggestion";
import { api, qs } from "@/api/client";
import type { ItemRefSuggestion } from "./extensions";
import { tx } from "@/lib/i18n";

interface ItemsPage { items: { key: string; title: string; type_key: string }[] }

export function itemSuggestion(projectKey: string): Omit<SuggestionOptions<ItemRefSuggestion>, "editor"> {
  return {
    char: "#",
    allowSpaces: false,
    items: async ({ query }) => {
      if (!projectKey) return [];
      try {
        const res = await api.get<ItemsPage>(`/projects/${projectKey}/items${qs({ q: query || undefined, limit: 8, sort: "-updated" })}`);
        return res.items.map((i) => ({ key: i.key, title: i.title, type: i.type_key }));
      } catch {
        return [];
      }
    },
    command: ({ editor, range, props }) => {
      editor.chain().focus().insertContentAt(range, [
        { type: "itemRef", attrs: { key: props.key } }, { type: "text", text: " " },
      ]).run();
    },
    render: () => {
      let el: HTMLDivElement | null = null;
      let selected = 0;
      let current: SuggestionProps<ItemRefSuggestion> | null = null;

      const draw = () => {
        if (!el || !current) return;
        el.innerHTML = "";
        if (!current.items.length) {
          const empty = document.createElement("div");
          empty.className = "item-suggest-empty";
          empty.textContent = tx("No matching items");
          el.appendChild(empty);
        }
        current.items.forEach((item, i) => {
          const row = document.createElement("button");
          row.type = "button";
          row.className = `item-suggest-row${i === selected ? " is-selected" : ""}`;
          row.setAttribute("data-testid", `suggest-${item.key}`);
          const key = document.createElement("span");
          key.className = "item-suggest-key";
          key.textContent = item.key;
          const title = document.createElement("span");
          title.textContent = item.title;
          row.append(key, title);
          row.onmousedown = (e) => { e.preventDefault(); current?.command(item); };
          el!.appendChild(row);
        });
        const rect = current.clientRect?.();
        if (rect) {
          const virtual = { getBoundingClientRect: () => rect };
          computePosition(virtual, el, { placement: "bottom-start", middleware: [offset(4), flip(), shift({ padding: 8 })] })
            .then(({ x, y }) => { if (el) Object.assign(el.style, { left: `${x}px`, top: `${y}px` }); });
        }
      };

      return {
        onStart: (props) => {
          current = props;
          selected = 0;
          el = document.createElement("div");
          el.className = "item-suggest";
          el.setAttribute("data-testid", "item-suggest");
          document.body.appendChild(el);
          draw();
        },
        onUpdate: (props) => { current = props; selected = 0; draw(); },
        onKeyDown: ({ event }) => {
          if (!current) return false;
          if (event.key === "ArrowDown") { selected = (selected + 1) % Math.max(current.items.length, 1); draw(); return true; }
          if (event.key === "ArrowUp") { selected = (selected - 1 + current.items.length) % Math.max(current.items.length, 1); draw(); return true; }
          if (event.key === "Enter" || event.key === "Tab") {
            const item = current.items[selected];
            if (item) { current.command(item); return true; }
          }
          if (event.key === "Escape") { el?.remove(); el = null; return true; }
          return false;
        },
        onExit: () => { el?.remove(); el = null; current = null; },
      };
    },
  };
}
