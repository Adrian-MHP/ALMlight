// The rich-text schema shared by every editor (standalone and live) and by the deterministic session seed.
// Node and mark names are the contract with the server, which reads the shared document (collab/serialize.py).
import { mergeAttributes, Node, type Extensions } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Image from "@tiptap/extension-image";
import { TableKit } from "@tiptap/extension-table";
import Highlight from "@tiptap/extension-highlight";
import Subscript from "@tiptap/extension-subscript";
import Superscript from "@tiptap/extension-superscript";
import TextAlign from "@tiptap/extension-text-align";
import { Placeholder } from "@tiptap/extensions";
import Suggestion, { type SuggestionOptions } from "@tiptap/suggestion";
import { getUploadImageExtension } from "@mantine/tiptap";
import Document from "@tiptap/extension-document";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import { tx } from "@/lib/i18n";

export interface ItemRefSuggestion { key: string; title: string; type?: string }

/** Inline reference to another item (`#SYS-12`), stored as `<span data-type="item-ref" data-key="SYS-12">`. */
export const ItemRef = Node.create<{ suggestion: Omit<SuggestionOptions<ItemRefSuggestion>, "editor"> | null }>({
  name: "itemRef",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addOptions() {
    return { suggestion: null };
  },
  addAttributes() {
    return {
      key: {
        default: null,
        parseHTML: (el) => el.getAttribute("data-key"),
        renderHTML: (attrs) => ({ "data-key": attrs.key }),
      },
    };
  },
  parseHTML() {
    return [{ tag: 'span[data-type="item-ref"]' }];
  },
  renderHTML({ node, HTMLAttributes }) {
    return ["span", mergeAttributes({ "data-type": "item-ref", class: "item-ref" }, HTMLAttributes), node.attrs.key];
  },
  renderText({ node }) {
    return node.attrs.key;
  },
  addProseMirrorPlugins() {
    return this.options.suggestion ? [Suggestion({ editor: this.editor, ...this.options.suggestion })] : [];
  },
});

export interface BodyOptions {
  collaborative?: boolean;
  placeholder?: string;
  onImageUpload?: (file: File) => Promise<string>;
  onImageUploadError?: (file: File, error: unknown) => void;
  suggestion?: Omit<SuggestionOptions<ItemRefSuggestion>, "editor"> | null;
}

const noUpload = () => Promise.reject(new Error(tx("Image upload is not available here")));

/** Extensions of an item text. Options must not change the schema (all clients must build identical documents). */
export function bodyExtensions(opts: BodyOptions = {}): Extensions {
  return [
    StarterKit.configure({
      undoRedo: opts.collaborative ? false : undefined,
      trailingNode: false,
      heading: { levels: [1, 2, 3, 4, 5, 6] },
      link: { openOnClick: false, autolink: true, protocols: ["http", "https", "mailto"], defaultProtocol: "https" },
    }),
    getUploadImageExtension(Image, {
      onImageUpload: opts.onImageUpload ?? noUpload,
      onImageUploadError: opts.onImageUploadError,
    }).configure({ inline: false, allowBase64: false }),
    TableKit.configure({ table: { resizable: false } }),
    Highlight,
    Subscript,
    Superscript,
    TextAlign.configure({ types: ["heading", "paragraph"] }),
    Placeholder.configure({ placeholder: opts.placeholder ?? tx("Write the text… (type # to reference an item)") }),
    ItemRef.configure({ suggestion: opts.suggestion ?? null }),
  ];
}

/** A single-line title: one paragraph of plain text. */
export const TitleDocument = Document.extend({ content: "paragraph" });

export function titleExtensions(placeholder = tx("Title")): Extensions {
  return [TitleDocument, Paragraph, Text, Placeholder.configure({ placeholder })];
}
