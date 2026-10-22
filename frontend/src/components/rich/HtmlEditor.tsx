import { useMemo } from "react";
import { useEditor } from "@tiptap/react";
import { bodyExtensions } from "./extensions";
import { itemSuggestion } from "./suggestion";
import { EditorFrame, uploadError, uploadImage } from "./EditorFrame";

/** A standalone rich-text editor (e.g. the text of a new item); reports HTML on every change. */
export function HtmlEditor({ value, onChange, projectKey, testId, placeholder, minHeight = 140 }: {
  value: string; onChange: (html: string) => void; projectKey: string; testId?: string; placeholder?: string;
  minHeight?: number;
}) {
  const upload = useMemo(() => uploadImage(projectKey), [projectKey]);
  const editor = useEditor({
    extensions: bodyExtensions({ onImageUpload: upload, onImageUploadError: uploadError, suggestion: itemSuggestion(projectKey), placeholder }),
    content: value || "",
    onUpdate: ({ editor: e }) => onChange(e.isEmpty ? "" : e.getHTML()),
  }, [projectKey]);
  return <EditorFrame editor={editor} onImageUpload={upload} testId={testId} minHeight={minHeight} />;
}
